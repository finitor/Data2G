#include <jni.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <stdexcept>
#include <string>

#include "runner.hpp"
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
extern "C" JNIEXPORT jstring JNICALL
Java_org_cleverdomain_data2g_lab_MainActivity_nativeRun(JNIEnv* env, jobject self, jstring channel,
                                                     jdouble snr, jlong seed, jint bytes, jint horizon, jint threads, jboolean paced) {
    try {
        if (threads < 1 || threads > 32 || bytes < 1 || seed < 0) throw std::invalid_argument("invalid run settings");
        data2g::pool::set_threads(threads);
        data2g::lab::Options o;
        o.channel = utf(env, channel);
        o.snr_db = snr;
        o.seed = static_cast<std::uint64_t>(seed);
        o.bytes_each_way = static_cast<std::size_t>(bytes);
        o.horizon_s = horizon;
        o.paced = paced;
        const jclass cls = env->GetObjectClass(self);
        const jmethodID notify = env->GetMethodID(cls, "progress", "(Ljava/lang/String;)V");
        if (!notify) return nullptr;
        const auto result = data2g::lab::run(o, cancelled, [&](const std::string& s) {
            jstring text = env->NewStringUTF(s.c_str());
            if (!text) throw std::runtime_error("cannot allocate progress string");
            env->CallVoidMethod(self, notify, text);
            env->DeleteLocalRef(text);
            if (env->ExceptionCheck()) throw std::runtime_error("progress callback failed");
        });
        return env->NewStringUTF(result.c_str());
    } catch (const std::exception& e) {
        if (!env->ExceptionCheck()) env->ThrowNew(env->FindClass("java/lang/RuntimeException"), e.what());
        return nullptr;
    }
}
