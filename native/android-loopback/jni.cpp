#include <jni.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <stdexcept>
#include <string>

#include "runner.hpp"
#include "campaign.hpp"
#include "arq/modes.hpp"
#include "util/pool.hpp"

namespace {
std::atomic_bool cancelled{false};
std::string utf(JNIEnv* env, jstring s) {
    const char* chars = env->GetStringUTFChars(s, nullptr);
    if (!chars) throw std::runtime_error("cannot read Java string");
    std::string result(chars);
    env->ReleaseStringUTFChars(s, chars);
    return result;
}
}
extern "C" JNIEXPORT void JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeCancel(JNIEnv*, jobject) { cancelled = true; }
extern "C" JNIEXPORT void JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeReset(JNIEnv*, jobject) { cancelled = false; }
extern "C" JNIEXPORT jint JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeDefaultThreads(JNIEnv*, jobject) { return data2g::pool::default_threads(); }
extern "C" JNIEXPORT jstring JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeRevision(JNIEnv* env, jobject) { return env->NewStringUTF(DATA2G_LAB_REVISION); }
extern "C" JNIEXPORT jstring JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeCpmModes(JNIEnv* env, jobject) {
    std::string out = "[";
    for (const auto& mode : data2g::arq::modes()) if (mode.is_cpm()) {
        if (out.size() > 1) out += ',';
        out += '"'; out += mode.name; out += '"';
    }
    out += ']'; return env->NewStringUTF(out.c_str());
}
extern "C" JNIEXPORT jint JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeCampaignSize(JNIEnv* env, jobject, jstring name, jint trials) {
    try { return static_cast<jint>(data2g::lab::campaign_size(utf(env, name), trials)); }
    catch (const std::exception& e) { env->ThrowNew(env->FindClass("java/lang/IllegalArgumentException"), e.what()); return 0; }
}
extern "C" JNIEXPORT jstring JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeCampaignCase(JNIEnv* env, jobject, jstring name, jint ordinal, jint trials, jlong seed) {
    try {
        const auto c = data2g::lab::campaign_case(utf(env, name), ordinal, trials, seed);
        return env->NewStringUTF(data2g::lab::campaign_case_json(c).c_str());
    } catch (const std::exception& e) { env->ThrowNew(env->FindClass("java/lang/IllegalArgumentException"), e.what()); return nullptr; }
}
extern "C" JNIEXPORT jstring JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeRun(JNIEnv* env, jobject self, jstring kind, jstring channel, jstring mode,
                                                     jdouble snr, jlong seed, jint bytes, jint horizon, jint threads, jboolean paced, jdouble cfo) {
    try {
        if (threads < 0 || threads > 32 || bytes < 1 || seed < 0) throw std::invalid_argument("invalid run settings");
        data2g::pool::set_threads(threads);
        data2g::lab::Options o;
        o.channel = utf(env, channel);
        o.fixed_mode = utf(env, mode);
        o.snr_db = snr;
        o.seed = static_cast<std::uint64_t>(seed);
        o.bytes_each_way = static_cast<std::size_t>(bytes);
        o.horizon_s = horizon;
        o.paced = paced;
        o.cfo_hz = cfo;
        const jclass cls = env->GetObjectClass(self);
        const jmethodID notify = env->GetMethodID(cls, "progress", "(Ljava/lang/String;)V");
        const jmethodID notifyTransfer = env->GetMethodID(cls, "transferProgress", "(Ljava/lang/String;)V");
        if (!notify || !notifyTransfer) return nullptr;
        auto send = [&](jmethodID method, const std::string& s) {
            jstring text = env->NewStringUTF(s.c_str());
            if (!text) throw std::runtime_error("cannot allocate progress string");
            env->CallVoidMethod(self, method, text);
            env->DeleteLocalRef(text);
            if (env->ExceptionCheck()) throw std::runtime_error("progress callback failed");
        };
        const auto type = utf(env, kind);
        std::string result;
        if (type == "two_endpoint_loopback") result = data2g::lab::run(o, cancelled,
            [&](const std::string& s) { send(notify, s); }, [&](const std::string& s) { send(notifyTransfer, s); });
        else if (type == "cpm_receiver_burst") result = data2g::lab::run_cpm_burst(o, cancelled,
            [&](const std::string& s) { send(notify, s); });
        else throw std::invalid_argument("unknown native workload kind");
        result.pop_back();
        result += ",\"requested_pool_threads\":" + std::to_string(threads) + ",\"default_pool_threads\":"
                + std::to_string(data2g::pool::default_threads()) + "}";
        return env->NewStringUTF(result.c_str());
    } catch (const std::exception& e) {
        if (!env->ExceptionCheck()) env->ThrowNew(env->FindClass("java/lang/RuntimeException"), e.what());
        return nullptr;
    }
}
