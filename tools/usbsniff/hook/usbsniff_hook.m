// usbsniff_hook.m - listen-only logger for PTP traffic sent through Apple's ImageCaptureCore.
//
// Loaded with DYLD_INSERT_LIBRARIES into a re-signed COPY of a program (never the installed original).
// It wraps -[ICCameraDevice requestSendPTPCommand:...] (both the block and the delegate variant) and the
// delegate callback -cameraDevice:didReceivePTPEvent:, and appends one JSON object per line to the file
// named by USBSNIFF_LOG. It never sends anything itself: every call is passed on unchanged.
//
// Environment:
//   USBSNIFF_LOG  output file (JSON lines); default /tmp/usbsniff-<pid>.jsonl
//   USBSNIFF_MAX  max payload bytes stored per data phase (default 4096; full length is always recorded)
//
// Build: see tools/usbsniff/README.md (python -m usbsniff hook build).

#import <Foundation/Foundation.h>
#import <ImageCaptureCore/ImageCaptureCore.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <stdio.h>
#include <unistd.h>

static FILE *g_log;
static dispatch_queue_t g_queue;
static NSUInteger g_max = 4096;
static volatile int64_t g_seq;

static NSString *hexOf(NSData *d) {
    if (!d) return nil;
    NSUInteger n = MIN(d.length, g_max);
    const uint8_t *p = d.bytes;
    NSMutableString *s = [NSMutableString stringWithCapacity:n * 2];
    for (NSUInteger i = 0; i < n; i++) [s appendFormat:@"%02x", p[i]];
    return s;
}

static void emit(NSDictionary *rec) {
    NSMutableDictionary *r = [rec mutableCopy];
    r[@"t"] = @([[NSDate date] timeIntervalSince1970]);
    r[@"pid"] = @(getpid());
    dispatch_async(g_queue, ^{
        NSData *j = [NSJSONSerialization dataWithJSONObject:r options:0 error:nil];
        if (!j || !g_log) return;
        fwrite(j.bytes, 1, j.length, g_log);
        fputc('\n', g_log);
        fflush(g_log);
    });
}

static void putData(NSMutableDictionary *r, NSString *key, NSData *d) {
    if (!d) return;
    r[key] = hexOf(d);
    r[[key stringByAppendingString:@"_len"]] = @(d.length);
}

static void logRequest(int64_t seq, NSData *cmd, NSData *outData) {
    NSMutableDictionary *r = [@{@"kind": @"cmd", @"seq": @(seq)} mutableCopy];
    putData(r, @"cmd", cmd);
    putData(r, @"out", outData);
    emit(r);
}

static void logReply(int64_t seq, NSData *inData, NSData *resp, NSError *err) {
    NSMutableDictionary *r = [@{@"kind": @"resp", @"seq": @(seq)} mutableCopy];
    putData(r, @"in", inData);
    putData(r, @"resp", resp);
    if (err) r[@"err"] = err.description;
    emit(r);
}

// ---- block variant ---------------------------------------------------------------------------
typedef void (^PTPCompletion)(NSData *, NSData *, NSError *);
static void (*orig_block)(id, SEL, NSData *, NSData *, PTPCompletion);

static void hook_block(id self, SEL _cmd, NSData *cmd, NSData *outData, PTPCompletion completion) {
    int64_t seq = __sync_add_and_fetch(&g_seq, 1);
    logRequest(seq, cmd, outData);
    PTPCompletion wrapped = ^(NSData *inData, NSData *resp, NSError *err) {
        logReply(seq, inData, resp, err);
        if (completion) completion(inData, resp, err);
    };
    orig_block(self, _cmd, cmd, outData, wrapped);
}

// ---- delegate variant ------------------------------------------------------------------------
@interface USBSniffProxy : NSObject
@property (nonatomic, strong) id target;
@property (nonatomic) SEL selector;
@property (nonatomic) void *context;
@property (nonatomic) int64_t seq;
@end

static NSMutableSet *g_proxies;

@implementation USBSniffProxy
- (void)usbsniff_didSend:(NSData *)command inData:(NSData *)data response:(NSData *)response
                   error:(NSError *)error contextInfo:(void *)contextInfo {
    logReply(self.seq, data, response, error);
    if (self.target && self.selector && [self.target respondsToSelector:self.selector]) {
        ((void (*)(id, SEL, NSData *, NSData *, NSData *, NSError *, void *))objc_msgSend)(
            self.target, self.selector, command, data, response, error, self.context);
    }
    @synchronized (g_proxies) { [g_proxies removeObject:self]; }
}
@end

static void (*orig_delegate)(id, SEL, NSData *, NSData *, id, SEL, void *);

static void hook_delegate(id self, SEL _cmd, NSData *cmd, NSData *outData, id delegate, SEL sel, void *ctx) {
    int64_t seq = __sync_add_and_fetch(&g_seq, 1);
    logRequest(seq, cmd, outData);
    USBSniffProxy *p = [USBSniffProxy new];
    p.target = delegate; p.selector = sel; p.context = ctx; p.seq = seq;
    @synchronized (g_proxies) { [g_proxies addObject:p]; }
    orig_delegate(self, _cmd, cmd, outData, p, @selector(usbsniff_didSend:inData:response:error:contextInfo:), ctx);
}

// ---- events ----------------------------------------------------------------------------------
static NSMutableDictionary *g_eventImps;  // class name -> original IMP

static void hook_event(id self, SEL _cmd, id camera, NSData *event) {
    NSMutableDictionary *r = [@{@"kind": @"event"} mutableCopy];
    putData(r, @"event", event);
    emit(r);
    IMP orig = NULL;
    for (Class c = object_getClass(self); c && !orig; c = class_getSuperclass(c)) {
        @synchronized (g_eventImps) { orig = [g_eventImps[NSStringFromClass(c)] pointerValue]; }
    }
    if (orig) ((void (*)(id, SEL, id, NSData *))orig)(self, _cmd, camera, event);
}

static void hookEventsOf(id delegate) {
    if (!delegate) return;
    SEL sel = @selector(cameraDevice:didReceivePTPEvent:);
    Class c = object_getClass(delegate);
    Method m = class_getInstanceMethod(c, sel);
    if (!m) return;
    // find the class that actually implements it, hook it there once
    Class owner = c;
    while (class_getSuperclass(owner) && class_getInstanceMethod(class_getSuperclass(owner), sel) == m)
        owner = class_getSuperclass(owner);
    NSString *key = NSStringFromClass(owner);
    @synchronized (g_eventImps) {
        if (g_eventImps[key]) return;
        IMP old = method_setImplementation(m, (IMP)hook_event);
        g_eventImps[key] = [NSValue valueWithPointer:old];
    }
    emit(@{@"kind": @"note", @"msg": [@"event hook on " stringByAppendingString:key]});
}

static void (*orig_setDelegate)(id, SEL, id);
static void hook_setDelegate(id self, SEL _cmd, id delegate) {
    hookEventsOf(delegate);
    orig_setDelegate(self, _cmd, delegate);
}

// ---- install ---------------------------------------------------------------------------------
static IMP swap(Class c, SEL sel, IMP repl) {
    Method m = class_getInstanceMethod(c, sel);
    if (!m) return NULL;
    return method_setImplementation(m, repl);
}

__attribute__((constructor)) static void usbsniff_init(void) {
    const char *path = getenv("USBSNIFF_LOG");
    char fallback[256];
    if (!path || !*path) { snprintf(fallback, sizeof fallback, "/tmp/usbsniff-%d.jsonl", getpid()); path = fallback; }
    const char *mx = getenv("USBSNIFF_MAX");
    if (mx && atol(mx) > 0) g_max = (NSUInteger)atol(mx);
    g_log = fopen(path, "a");
    g_queue = dispatch_queue_create("usbsniff.log", DISPATCH_QUEUE_SERIAL);
    g_proxies = [NSMutableSet set];
    g_eventImps = [NSMutableDictionary dictionary];

    Class cam = objc_getClass("ICCameraDevice");
    Class dev = objc_getClass("ICDevice");
    NSMutableArray *hooked = [NSMutableArray array];
    orig_block = (void *)swap(cam, @selector(requestSendPTPCommand:outData:completion:), (IMP)hook_block);
    if (orig_block) [hooked addObject:@"block"];
    orig_delegate = (void *)swap(cam, @selector(requestSendPTPCommand:outData:sendCommandDelegate:didSendCommandSelector:contextInfo:), (IMP)hook_delegate);
    if (orig_delegate) [hooked addObject:@"delegate"];
    orig_setDelegate = (void *)swap(dev, @selector(setDelegate:), (IMP)hook_setDelegate);
    if (orig_setDelegate) [hooked addObject:@"setDelegate"];
    NSString *exe = [NSProcessInfo processInfo].processName ?: @"?";
    emit(@{@"kind": @"note", @"msg": [NSString stringWithFormat:@"usbsniff loaded in %@, hooks: %@", exe,
                                     [hooked componentsJoinedByString:@","]]});
}
