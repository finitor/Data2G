package org.cleverdomain.data2g.lab;

import android.app.Activity;
import android.app.ActivityManager;
import android.content.Intent;
import android.os.Build;
import android.os.Debug;
import android.os.Bundle;
import android.os.PowerManager;
import android.view.View;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.text.InputType;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Thin front end: the same runner and result schema as the desktop CLI. */
public final class MainActivity extends Activity {
    static { System.loadLibrary("data2g_lab"); }
    private native void nativeReset();
    private native void nativeCancel();
    private native String nativeRun(String channel, double snr, long seed, int bytes, int horizon, int threads);

    private final String[] channels = {"clean", "awgn", "mpg", "mpp", "mpd", "nvis", "hilat"};
    private Spinner channel;
    private EditText snr, seed, bytes, horizon, threads;
    private TextView status, results;
    private Button run, suite, stop, export;
    private volatile boolean running;
    private volatile boolean stopRequested;
    private volatile boolean destroyed;
    private String lastJson = "";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(16 * getResources().getDisplayMetrics().density);
        body.setPadding(pad, pad, pad, pad);
        scroll.addView(body);
        TextView title = label(body, "Data2G Lab");
        title.setTextSize(25);
        label(body, "Two native modems over a simulated HF channel. No radio required.\n"
                + "Virtual time: timing results are not a real-time qualification.");
        channel = new Spinner(this);
        channel.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, channels));
        body.addView(channel);
        snr = field(body, "SNR, dB in 2500 Hz (unused for clean)", "12", true);
        seed = field(body, "Seed", "1", false);
        bytes = field(body, "Bytes each way", "64", false);
        horizon = field(body, "Maximum simulated seconds (1–600)", "180", false);
        threads = field(body, "Modem pool threads (1–32)", "1", false);
        run = button(body, "Run selected case", v -> start(false));
        suite = button(body, "Quick suite: clean, AWGN, poor multipath", v -> start(true));
        stop = button(body, "Cancel", v -> { stopRequested = true; nativeCancel(); });
        stop.setEnabled(false);
        export = button(body, "Export JSON results", v -> {
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json")
                    .addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, "data2g-lab-results.json");
            startActivityForResult(i, 1);
        });
        export.setEnabled(false);
        status = label(body, "Ready. Keep this screen visible during a run; leaving cancels it.");
        results = label(body, "");
        results.setTextIsSelectable(true);
        setContentView(scroll);
        Intent intent = getIntent();
        if (intent.getBooleanExtra("auto", false)) {
            String selected = intent.getStringExtra("channel");
            for (int k = 0; k < channels.length; ++k) if (channels[k].equals(selected)) channel.setSelection(k);
            snr.setText(intent.getStringExtra("snr") == null ? "12" : intent.getStringExtra("snr"));
            seed.setText(String.valueOf(intent.getLongExtra("seed", 1)));
            bytes.setText(String.valueOf(intent.getIntExtra("bytes", 64)));
            horizon.setText(String.valueOf(intent.getIntExtra("horizon", 180)));
            threads.setText(String.valueOf(intent.getIntExtra("threads", 1)));
            body.post(() -> start(intent.getBooleanExtra("suite", false)));
        }
    }
    private TextView label(LinearLayout parent, String text) {
        TextView view = new TextView(this);
        view.setText(text);
        parent.addView(view);
        return view;
    }
    private EditText field(LinearLayout parent, String name, String value, boolean signed) {
        label(parent, name);
        EditText view = new EditText(this);
        view.setInputType(InputType.TYPE_CLASS_NUMBER | (signed ? InputType.TYPE_NUMBER_FLAG_SIGNED | InputType.TYPE_NUMBER_FLAG_DECIMAL : 0));
        view.setSingleLine(true);
        view.setText(value);
        parent.addView(view);
        return view;
    }
    private Button button(LinearLayout parent, String name, View.OnClickListener action) {
        Button b = new Button(this);
        b.setText(name);
        b.setOnClickListener(action);
        parent.addView(b);
        return b;
    }
    // JNI calls this on the Java worker, never on Android's main thread.
    public void progress(String text) {
        runOnUiThread(() -> { if (!destroyed) status.setText(text); });
    }
    private JSONObject device() throws Exception {
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
        getSystemService(ActivityManager.class).getMemoryInfo(memory);
        Debug.MemoryInfo process = new Debug.MemoryInfo();
        Debug.getMemoryInfo(process);
        return new JSONObject().put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL)
                .put("android", Build.VERSION.RELEASE).put("api", Build.VERSION.SDK_INT)
                .put("abis", new JSONArray(Build.SUPPORTED_ABIS)).put("memory_total_bytes", memory.totalMem)
                .put("memory_available_bytes", memory.availMem)
                .put("app_pss_bytes", process.getTotalPss() * 1024L)
                .put("app_private_dirty_bytes", process.getTotalPrivateDirty() * 1024L)
                .put("thermal_status", getSystemService(PowerManager.class).getCurrentThermalStatus());
    }
    private void start(boolean quick) {
        if (running) return;
        try {
            final double db = Double.parseDouble(snr.getText().toString());
            final long firstSeed = Long.parseLong(seed.getText().toString());
            final int count = Integer.parseInt(bytes.getText().toString());
            final int seconds = Integer.parseInt(horizon.getText().toString());
            final int pool = Integer.parseInt(threads.getText().toString());
            if (!Double.isFinite(db) || db < -30 || db > 60 || firstSeed < 0 || count < 1 || count > 65536
                    || seconds < 1 || seconds > 600 || pool < 1 || pool > 32)
                throw new IllegalArgumentException("Check SNR -30..60, seed >=0, bytes 1..65536, seconds 1..600, threads 1..32.");
            final String[] selected = quick ? new String[]{"clean", "awgn", "mpp"} : new String[]{channels[channel.getSelectedItemPosition()]};
            final JSONObject initialDevice = device();
            final long started = System.currentTimeMillis();
            running = true;
            stopRequested = false;
            nativeReset();
            run.setEnabled(false); suite.setEnabled(false); export.setEnabled(false); stop.setEnabled(true);
            results.setText(""); status.setText("Starting…");
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            new Thread(() -> {
                JSONArray trials = new JSONArray();
                StringBuilder summary = new StringBuilder();
                try {
                    for (String name : selected) {
                        if (stopRequested) break;
                        JSONObject trial = new JSONObject(nativeRun(name, db, firstSeed, count, seconds, pool));
                        trials.put(trial);
                        JSONObject report = new JSONObject().put("schema", 1).put("started_utc_ms", started)
                                .put("device_start", initialDevice).put("device_latest", device()).put("trials", trials);
                        String json = report.toString(2);
                        File dir = getExternalFilesDir(null);
                        if (dir == null) throw new IllegalStateException("result storage unavailable");
                        save(new File(dir, "run-" + started + ".json"), json);
                        save(new File(dir, "latest.json"), json);
                        summary.append(name).append(": ").append(trial.getString("outcome"))
                                .append("\n  Verified bytes A/B: ").append(trial.getInt("verified_at_a"))
                                .append(" / ").append(trial.getInt("verified_at_b"))
                                .append("\n  Simulated / wall: ").append(trial.getDouble("simulated_s"))
                                .append(" / ").append(trial.getDouble("wall_s"))
                                .append(" s\n  Process peak RAM: ").append(trial.getLong("process_lifetime_peak_rss_bytes") / 1048576)
                                .append(" MiB\n\n");
                        runOnUiThread(() -> {
                            if (!destroyed) { lastJson = json; results.setText(summary.toString()); }
                        });
                    }
                    progress(stopRequested ? "Cancelled; completed trial records saved." : "Finished. Results saved; export to share.");
                } catch (Exception e) { progress("Error: " + e.getMessage()); }
                finally {
                    running = false;
                    runOnUiThread(() -> {
                        if (!destroyed) {
                            run.setEnabled(true); suite.setEnabled(true); stop.setEnabled(false); export.setEnabled(!lastJson.isEmpty());
                            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                        }
                    });
                }
            }, "data2g-lab").start();
        } catch (Exception e) { status.setText(e.getMessage()); }
    }
    private void save(File file, String json) throws Exception {
        File temp = new File(file.getParentFile(), file.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(temp)) {
            out.write(json.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
        if (!temp.renameTo(file)) throw new IllegalStateException("cannot save " + file);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 1 && result == RESULT_OK && data != null && data.getData() != null) {
            try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                if (out == null) throw new IllegalStateException("cannot open export");
                out.write(lastJson.getBytes(StandardCharsets.UTF_8));
                status.setText("Exported.");
            } catch (Exception e) { status.setText("Export failed: " + e.getMessage()); }
        }
    }
    @Override protected void onStop() {
        if (running) { stopRequested = true; nativeCancel(); }
        super.onStop();
    }
    @Override protected void onDestroy() {
        destroyed = true;
        if (running) { stopRequested = true; nativeCancel(); }
        super.onDestroy();
    }
}
