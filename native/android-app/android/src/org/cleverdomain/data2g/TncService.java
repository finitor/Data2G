package org.cleverdomain.data2g;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * Keeps the modem alive independently of any screen (SSTVAE's ListenerService).
 *
 * <p>The modem belongs to this service: the UI asks it to start and stop, and
 * only it calls into the native modem to do either. It runs on with the app in
 * the background (TncActivity has what a swipe from Recents does). It holds no state of
 * its own: the notification is read from the native modem each time it is
 * drawn, and the service stops itself once the modem has stopped, whether by
 * the Stop action, the app's Stop button, or a start that failed.
 */
public class TncService extends Service {
    private static final String CHANNEL_ID = "data2g.modem";
    private static final int NOTIFICATION_ID = 1;
    private static final String ACTION_STOP_ALL = "org.cleverdomain.data2g.STOP_ALL";
    private static final String ACTION_START = "org.cleverdomain.data2g.START";
    private static final String ACTION_RADIO_START = "org.cleverdomain.data2g.RADIO_START";
    private static final String ACTION_RADIO_STOP = "org.cleverdomain.data2g.RADIO_STOP";
    private static final String ACTION_RADIO_RESTART = "org.cleverdomain.data2g.RADIO_RESTART";
    private static final String ACTION_STOP = "org.cleverdomain.data2g.STOP";
    private static final long REFRESH_MS = 1000;

    private static native void nativeStart();
    private static native void nativeStop();
    private static native void nativeStopNow();
    private static native void nativeStartRadio();
    private static native void nativeStopRadio();
    private static native boolean nativeRadioActive();
    private static native String nativeRadioStatus();
    /** 0 stopped, 1 starting, 2 running. */
    private static native int nativeState();
    private static native String nativeStatusLine();

    private final Handler handler = new Handler(Looper.getMainLooper());
    private static volatile boolean active = false;  // radio and/or modem service is active
    private String shown = "";

    private final Runnable refresh = new Runnable() {
        @Override
        public void run() {
            if (!active) return;
            boolean modem = nativeState() != 0;
            boolean radio = nativeRadioActive();
            if (!modem && !radio) { finish(); return; }
            String text = modem ? nativeStatusLine() : nativeRadioStatus();
            startForeground(NOTIFICATION_ID, notification(text), serviceTypes(modem));
            if (!text.equals(shown)) {
                shown = text;
                NotificationManager nm = getSystemService(NotificationManager.class);
                if (nm != null) nm.notify(NOTIFICATION_ID, notification(text));
            }
            handler.postDelayed(this, REFRESH_MS);
        }
    };

    /** From the activity, while it is in the foreground (a microphone service may only start then). */
    public static void startModem(Context context) {
        context.startForegroundService(new Intent(context, TncService.class).setAction(ACTION_START));
    }

    public static void startRadio(Context context) {
        context.startForegroundService(new Intent(context, TncService.class).setAction(ACTION_RADIO_START));
    }
    public static void stopRadio(Context context) {
        if (active) context.startService(new Intent(context, TncService.class).setAction(ACTION_RADIO_STOP));
    }
    public static void restartRadio(Context context) {
        context.startForegroundService(new Intent(context, TncService.class).setAction(ACTION_RADIO_RESTART));
    }

    /**
     * Stops the modem and waits for it (a few seconds at most), then the service:
     * for TncActivity, whose destroy ends the process right after.
     */
    public static void stopNow(Context context) {
        if (!active) return;
        active = false;
        nativeStopNow();
        context.stopService(new Intent(context, TncService.class));
    }

    public static void stopModem(Context context) {
        context.startService(new Intent(context, TncService.class).setAction(ACTION_STOP));
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;  // the UI reads the modem through its own JNI
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null ? intent.getAction() : null;
        boolean modemStart = ACTION_START.equals(action);
        boolean radioStart = ACTION_RADIO_START.equals(action) || ACTION_RADIO_RESTART.equals(action);
        if (modemStart || radioStart) {
            createChannel();
            startForeground(NOTIFICATION_ID, notification("Starting…"), serviceTypes(modemStart || nativeState() != 0));
            if (ACTION_RADIO_RESTART.equals(action)) nativeStopRadio();
            if (radioStart) nativeStartRadio();
            if (modemStart) nativeStart();
        } else if (ACTION_STOP.equals(action)) {
            nativeStop(); // radio service remains available
        } else if (ACTION_RADIO_STOP.equals(action)) {
            nativeStopRadio();
        } else {
            nativeStop();
            nativeStopRadio();
            // Keep the foreground service until native shutdown completes.
        }
        active = true;
        handler.removeCallbacks(refresh);
        handler.postDelayed(refresh, REFRESH_MS);
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        if (active) { nativeStop(); nativeStopRadio(); }
        active = false;
        handler.removeCallbacks(refresh);
        super.onDestroy();
    }

    private void finish() {
        active = false;
        handler.removeCallbacks(refresh);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    /**
     * Microphone to receive, media playback to transmit. Microphone may not be
     * claimed without RECORD_AUDIO (API 34 throws), so it is dropped then; the
     * modem's own start will then say what is missing.
     */
    private int serviceTypes(boolean modem) {
        if (!modem) return ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
        int types = ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK;
        if (nativeRadioActive()) types |= ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            types |= ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE;
        }
        return types;
    }

    private void createChannel() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        // LOW: it changes with every connection and over; anything louder would be unbearable.
        NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "Radio and modem", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Shown while Data2G radio control or the modem is running");
        ch.setShowBadge(false);
        nm.createNotificationChannel(ch);
    }

    private int smallIcon() {
        int id = getResources().getIdentifier("ic_stat_data2g", "drawable", getPackageName());
        return id != 0 ? id : android.R.drawable.stat_sys_upload;
    }

    private Notification notification(String text) {
        Intent open = new Intent(this, TncActivity.class)
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent openPi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE);
        // Shut the modem down from the shade, without bringing the app back.
        // Request code 1, not 0: PendingIntents are told apart by code and target, and
        // sharing one with the content intent would make one silently become the other.
        PendingIntent stopPi = PendingIntent.getService(
                this, 1, new Intent(this, TncService.class).setAction(ACTION_STOP_ALL), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Data2G TNC")
                .setContentText(text)
                .setSmallIcon(smallIcon())
                .setContentIntent(openPi)
                .addAction(new Notification.Action.Builder(
                        Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                        "Stop all", stopPi).build())
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .build();
    }
}
