package org.cleverdomain.data2g.lab;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Build;
import android.os.Debug;
import android.os.Bundle;
import android.os.PowerManager;
import android.view.View;
import android.view.WindowManager;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.text.InputType;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Comparator;
import java.util.concurrent.atomic.AtomicBoolean;

/** Workload controls plus an offline viewer for current and saved JSON reports. */
public final class MainActivity extends Activity {
    static { System.loadLibrary("data2g_lab"); }
    private native void nativeReset();
    private native void nativeCancel();
    private native String nativeRun(String channel, double snr, long seed, int bytes, int horizon, int threads, boolean paced);
    private static final AtomicBoolean ENGINE_ACTIVE = new AtomicBoolean();
    private final String[] channels = {"clean", "awgn", "mpg", "mpp", "mpd", "nvis", "hilat"};
    private Spinner channel, mode;
    private EditText snr, seed, bytes, horizon, threads, repeats;
    private CheckBox profiling;
    private TextView status;
    private Button run, suite, stop, export, saved, open;
    private ScrollView formPage, reportPage;
    private ReportView viewer;
    private volatile TimelineSampler sampler;
    private volatile boolean running, stopRequested, destroyed;
    private String lastJson = "";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = column();
        label(root, "Data2G Lab · 2", 24);
        label(root, "Phone-only modem tests and resource profiling", 14);
        LinearLayout nav = new LinearLayout(this);
        root.addView(nav);
        button(nav, "Run", v -> page(false));
        button(nav, "Results & graphs", v -> page(true));
        status = label(root, "Ready. Leaving the app cancels a running test.", 14);
        FrameLayout pages = new FrameLayout(this);
        root.addView(pages, new LinearLayout.LayoutParams(-1, 0, 1));
        formPage = new ScrollView(this);
        LinearLayout form = column(); formPage.addView(form); pages.addView(formPage);
        label(form, "Workload: two-endpoint modem loopback", 18);
        label(form, "Includes two modems and a simulated channel. This is not a single-transceiver resource measurement.", 14);
        channel = new Spinner(this);
        channel.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item, channels));
        form.addView(channel);
        label(form, "Execution", 15);
        mode = new Spinner(this);
        mode.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{"Wall-clock paced profiling", "Unpaced stress / correctness"}));
        form.addView(mode);
        label(form, "Pacing reproduces duty cycle. It reports lateness but does not qualify live audio queues or deadlines.", 14);
        snr = field(form, "SNR, dB in 2500 Hz (unused for clean)", "12", true);
        seed = field(form, "First seed", "1", false);
        bytes = field(form, "Bytes each way", "64", false);
        horizon = field(form, "Maximum simulated seconds per case (1–600)", "180", false);
        threads = field(form, "Modem pool threads (1–32)", "1", false);
        repeats = field(form, "Repetitions per case (1–100; seed increments)", "1", false);
        profiling = new CheckBox(this); profiling.setText("Record CPU, memory and thermal timelines"); profiling.setChecked(true); form.addView(profiling);
        run = button(form, "Run selected case", v -> start(false));
        suite = button(form, "Quick suite: clean, AWGN, poor multipath", v -> start(true));
        stop = button(root, "Cancel run", v -> { stopRequested = true; nativeCancel(); }); stop.setVisibility(View.GONE);
        reportPage = new ScrollView(this);
        LinearLayout reports = column(); reportPage.addView(reports); pages.addView(reportPage);
        saved = button(reports, "Open saved run", v -> openSaved());
        open = button(reports, "Open JSON from Downloads / Files", v -> startActivityForResult(
                new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), 2));
        export = button(reports, "Export this report as JSON", v -> startActivityForResult(
                new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE)
                        .putExtra(Intent.EXTRA_TITLE, "data2g-lab-results.json"), 1));
        export.setEnabled(false);
        viewer = new ReportView(this); reports.addView(viewer);
        setContentView(root);
        page(false);
        File directory = getExternalFilesDir(null);
        if (directory != null && new File(directory, "latest.json").isFile()) {
            try (InputStream in = new FileInputStream(new File(directory, "latest.json"))) { display(read(in)); }
            catch (Exception e) { status.setText("Could not restore latest report: " + e.getMessage()); }
        }
        Intent intent = getIntent();
        if (Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null) {
            try (InputStream in = getContentResolver().openInputStream(intent.getData())) { display(read(in)); status.setText("Viewing imported report."); }
            catch (Exception e) { status.setText("Cannot open report: " + e.getMessage()); }
        }
        if (intent.getBooleanExtra("auto", false)) {
            String selected = intent.getStringExtra("channel");
            for (int k = 0; k < channels.length; ++k) if (channels[k].equals(selected)) channel.setSelection(k);
            snr.setText(intent.getStringExtra("snr") == null ? "12" : intent.getStringExtra("snr"));
            seed.setText(String.valueOf(intent.getLongExtra("seed", 1)));
            bytes.setText(String.valueOf(intent.getIntExtra("bytes", 64)));
            horizon.setText(String.valueOf(intent.getIntExtra("horizon", 180)));
            threads.setText(String.valueOf(intent.getIntExtra("threads", 1)));
            repeats.setText(String.valueOf(intent.getIntExtra("repeats", 1)));
            mode.setSelection(intent.getBooleanExtra("paced", true) ? 0 : 1);
            profiling.setChecked(intent.getBooleanExtra("profiling", true));
            root.post(() -> start(intent.getBooleanExtra("suite", false)));
        }
    }
    private LinearLayout column() {
        LinearLayout result = new LinearLayout(this); result.setOrientation(LinearLayout.VERTICAL);
        int pad = (int)(12 * getResources().getDisplayMetrics().density); result.setPadding(pad, pad, pad, pad); return result;
    }
    private void page(boolean reports) { formPage.setVisibility(reports ? View.GONE : View.VISIBLE); reportPage.setVisibility(reports ? View.VISIBLE : View.GONE); }
    private TextView label(LinearLayout parent, String text, int size) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); parent.addView(view); return view;
    }
    private EditText field(LinearLayout parent, String name, String value, boolean signed) {
        label(parent, name, 15); EditText view = new EditText(this);
        view.setInputType(InputType.TYPE_CLASS_NUMBER | (signed ? InputType.TYPE_NUMBER_FLAG_SIGNED | InputType.TYPE_NUMBER_FLAG_DECIMAL : 0));
        view.setSingleLine(true); view.setText(value); parent.addView(view); return view;
    }
    private Button button(LinearLayout parent, String name, View.OnClickListener action) {
        Button b = new Button(this); b.setText(name); b.setOnClickListener(action); parent.addView(b); return b;
    }
    public void progress(String text) { runOnUiThread(() -> { if (!destroyed) status.setText(text); }); }
    private JSONObject device() throws Exception {
        ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo(); getSystemService(ActivityManager.class).getMemoryInfo(memory);
        Debug.MemoryInfo process = new Debug.MemoryInfo(); Debug.getMemoryInfo(process);
        return new JSONObject().put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL)
                .put("android", Build.VERSION.RELEASE).put("api", Build.VERSION.SDK_INT)
                .put("abis", new JSONArray(Build.SUPPORTED_ABIS)).put("memory_total_bytes", memory.totalMem)
                .put("memory_available_bytes", memory.availMem).put("app_pss_bytes", process.getTotalPss() * 1024L)
                .put("app_private_dirty_bytes", process.getTotalPrivateDirty() * 1024L)
                .put("thermal_status", getSystemService(PowerManager.class).getCurrentThermalStatus());
    }
    private void enabled(boolean ready) {
        run.setEnabled(ready); suite.setEnabled(ready); open.setEnabled(ready); saved.setEnabled(ready);
        export.setEnabled(ready && !lastJson.isEmpty()); stop.setVisibility(ready ? View.GONE : View.VISIBLE);
    }
    private void start(boolean quick) {
        if (running) return;
        try {
            final double db = Double.parseDouble(snr.getText().toString());
            final long firstSeed = Long.parseLong(seed.getText().toString());
            final int count = Integer.parseInt(bytes.getText().toString()), seconds = Integer.parseInt(horizon.getText().toString());
            final int pool = Integer.parseInt(threads.getText().toString()), cycles = Integer.parseInt(repeats.getText().toString());
            if (!Double.isFinite(db) || db < -30 || db > 60 || firstSeed < 0 || firstSeed > Long.MAX_VALUE - 100 || count < 1 || count > 65536
                    || seconds < 1 || seconds > 600 || pool < 1 || pool > 32 || cycles < 1 || cycles > 100)
                throw new IllegalArgumentException("Check SNR -30..60, seed >=0, bytes 1..65536, seconds 1..600, threads 1..32, repetitions 1..100.");
            final String[] selected = quick ? new String[]{"clean", "awgn", "mpp"} : new String[]{channels[channel.getSelectedItemPosition()]};
            final boolean paced = mode.getSelectedItemPosition() == 0, collect = profiling.isChecked();
            final JSONObject initialDevice = device();
            final long started = System.currentTimeMillis();
            if (!ENGINE_ACTIVE.compareAndSet(false, true)) throw new IllegalStateException("Previous run is stopping; try again shortly.");
            running = true; stopRequested = false; nativeReset(); enabled(false);
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            page(true); status.setText("Starting…");
            new Thread(() -> {
                JSONArray trials = new JSONArray();
                TimelineSampler monitor = collect ? new TimelineSampler(this, () -> runOnUiThread(() -> {
                    TimelineSampler current = sampler;
                    if (!destroyed && current != null && reportPage.getVisibility() == View.VISIBLE) viewer.timeline(current.snapshot());
                })) : null;
                sampler = monitor;
                boolean failed = false;
                try {
                    if (monitor != null) monitor.start();
                    publish(report(started, initialDevice, trials, monitor, paced, cycles));
                    for (int cycle = 0; cycle < cycles && !stopRequested; ++cycle) {
                        for (String name : selected) {
                            if (stopRequested) break;
                            if (monitor != null) monitor.mark(name + " #" + (cycle + 1), "start");
                            JSONObject trial = new JSONObject(nativeRun(name, db, firstSeed + cycle, count, seconds, pool, paced));
                            trial.put("workload_kind", "two_endpoint_loopback").put("iteration", cycle + 1);
                            trials.put(trial);
                            if (monitor != null) monitor.mark(name + " #" + (cycle + 1), "end");
                            checkpoint(report(started, initialDevice, trials, monitor, paced, cycles), started);
                        }
                    }
                } catch (Exception e) {
                    failed = true;
                    try { trials.put(new JSONObject().put("workload_kind", "two_endpoint_loopback").put("outcome", "runtime_error").put("error", e.toString())); }
                    catch (Exception ignored) { }
                    progress("Run error: " + e.getMessage());
                } finally {
                    try {
                        if (monitor != null) monitor.finish();
                        checkpoint(report(started, initialDevice, trials, monitor, paced, cycles), started);
                    } catch (Exception e) { progress("Could not save final report: " + e.getMessage()); }
                    sampler = null; running = false; ENGINE_ACTIVE.set(false);
                    final String ending = failed ? "Run failed. See the saved error and partial graphs."
                            : stopRequested ? "Cancelled. Partial results and graphs saved." : "Finished. View results and graphs below.";
                    runOnUiThread(() -> {
                        if (!destroyed) {
                            enabled(true); getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                            status.setText(ending);
                        }
                    });
                }
            }, "data2g-lab").start();
        } catch (Exception e) { status.setText(e.getMessage()); }
    }
    private JSONObject report(long started, JSONObject initial, JSONArray trials, TimelineSampler monitor, boolean paced, int cycles) throws Exception {
        JSONObject r = new JSONObject().put("schema", 2).put("started_utc_ms", started).put("workload_kind", "two_endpoint_loopback")
                .put("resource_scope", "whole_app_two_modems_channel_ui_and_profiler")
                .put("requested_clock_mode", paced ? "wall_clock_paced" : "virtual_unpaced").put("requested_repetitions", cycles)
                .put("device_start", initial).put("device_latest", device()).put("trials", trials);
        if (monitor != null) r.put("profiling", monitor.snapshot());
        return r;
    }
    private void publish(JSONObject r) { final String text = r.toString(); runOnUiThread(() -> { if (!destroyed) { try { display(text); } catch (Exception e) { status.setText(e.getMessage()); } } }); }
    private void checkpoint(JSONObject report, long started) throws Exception {
        String json = report.toString(2); File dir = getExternalFilesDir(null);
        if (dir == null) throw new IllegalStateException("result storage unavailable");
        save(new File(dir, "run-" + started + ".json"), json); save(new File(dir, "latest.json"), json); publish(report);
    }
    private void display(String json) throws Exception {
        JSONObject report = new JSONObject(json); JSONArray trials = report.optJSONArray("trials");
        if (trials == null || trials.length() > 10000) throw new IllegalArgumentException("Not a supported Data2G Lab report.");
        JSONObject profile = report.optJSONObject("profiling");
        if (profile != null) {
            JSONArray samples = profile.optJSONArray("samples");
            if (samples != null) {
                if (samples.length() > 12000) throw new IllegalArgumentException("Too many timeline samples.");
                double previous = -1;
                for (int i = 0; i < samples.length(); ++i) {
                    JSONObject point = samples.optJSONObject(i);
                    double t = point == null ? Double.NaN : point.optDouble("elapsed_s", Double.NaN);
                    if (!Double.isFinite(t) || t < previous || t < 0) throw new IllegalArgumentException("Invalid timeline timestamps.");
                    previous = t;
                }
            }
        }
        viewer.report(report); lastJson = report.toString(2); export.setEnabled(!running); page(true);
    }
    private static String read(InputStream in) throws Exception {
        if (in == null) throw new IllegalArgumentException("Cannot open report.");
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int n;
        while ((n = in.read(buffer)) >= 0) { if (out.size() + n > 16 * 1024 * 1024) throw new IllegalArgumentException("Report exceeds 16 MiB."); out.write(buffer, 0, n); }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
    private void openSaved() {
        File dir = getExternalFilesDir(null); File[] files = dir == null ? null : dir.listFiles((d, name) -> name.startsWith("run-") && name.endsWith(".json"));
        if (files == null || files.length == 0) { status.setText("No saved runs yet."); return; }
        Arrays.sort(files, Comparator.comparing(File::getName).reversed());
        String[] names = new String[files.length];
        for (int i = 0; i < files.length; ++i) names[i] = files[i].getName();
        new AlertDialog.Builder(this).setTitle("Saved runs (newest first)").setItems(names, (dialog, which) -> {
            try (InputStream in = new FileInputStream(files[which])) { display(read(in)); status.setText("Viewing " + files[which].getName()); }
            catch (Exception e) { status.setText("Cannot open report: " + e.getMessage()); }
        }).show();
    }
    private void save(File file, String json) throws Exception {
        File temp = new File(file.getParentFile(), file.getName() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(temp)) { out.write(json.getBytes(StandardCharsets.UTF_8)); out.getFD().sync(); }
        if (!temp.renameTo(file)) throw new IllegalStateException("cannot save " + file);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        try {
            if (request == 1) {
                try (OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                    if (out == null) throw new IllegalStateException("cannot open export"); out.write(lastJson.getBytes(StandardCharsets.UTF_8)); status.setText("Exported.");
                }
            } else if (request == 2) {
                try (InputStream in = getContentResolver().openInputStream(data.getData())) { display(read(in)); status.setText("Viewing imported report."); }
            }
        } catch (Exception e) { status.setText("Report error: " + e.getMessage()); }
    }
    @Override protected void onStop() { if (running) { stopRequested = true; nativeCancel(); } super.onStop(); }
    @Override protected void onDestroy() { destroyed = true; if (running) { stopRequested = true; nativeCancel(); } super.onDestroy(); }
}
