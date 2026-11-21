// What TncService calls. Only the service starts and stops the modem (the
// UI asks the service), so the modem belongs to the one thing whose lifetime
// Android guarantees. Called on Android's main thread: everything here
// returns at once (modem.hpp).

#include <jni.h>

#include "modem.hpp"

using data2g::androidapp::Modem;
using data2g::androidapp::State;

extern "C" {

JNIEXPORT void JNICALL Java_org_cleverdomain_data2g_TncService_nativeStart(JNIEnv*, jclass) { Modem::instance().post_start(); }

JNIEXPORT void JNICALL Java_org_cleverdomain_data2g_TncService_nativeStop(JNIEnv*, jclass) { Modem::instance().post_stop(); }

JNIEXPORT void JNICALL Java_org_cleverdomain_data2g_TncService_nativeStartRadio(JNIEnv*, jclass) { Modem::instance().post_start_radio(); }
JNIEXPORT void JNICALL Java_org_cleverdomain_data2g_TncService_nativeStopRadio(JNIEnv*, jclass) { Modem::instance().post_stop_radio(); }
JNIEXPORT jboolean JNICALL Java_org_cleverdomain_data2g_TncService_nativeRadioActive(JNIEnv*, jclass) { return Modem::instance().radio_running(); }
JNIEXPORT jstring JNICALL Java_org_cleverdomain_data2g_TncService_nativeRadioStatus(JNIEnv* env, jclass) {
    return env->NewStringUTF(Modem::instance().radio_status().c_str());
}

// The one call here that waits (3 s at most): the activity is being destroyed for good.
JNIEXPORT void JNICALL Java_org_cleverdomain_data2g_TncService_nativeStopNow(JNIEnv*, jclass) { Modem::instance().stop_now(); }

// 0 stopped, 1 starting, 2 running.
JNIEXPORT jint JNICALL Java_org_cleverdomain_data2g_TncService_nativeState(JNIEnv*, jclass) {
    switch (Modem::instance().state()) {
        case State::Starting: return 1;
        case State::Running: return 2;
        default: return 0;
    }
}

JNIEXPORT jstring JNICALL Java_org_cleverdomain_data2g_TncService_nativeStatusLine(JNIEnv* env, jclass) {
    return env->NewStringUTF(Modem::instance().status_line().c_str());
}

}  // extern "C"
