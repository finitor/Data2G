package org.cleverdomain.data2g.lab;

import android.content.Context;
import android.graphics.Typeface;
import android.os.SystemClock;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayDeque;
import java.util.Locale;

/** Bounded live output; workers never enqueue one UI operation per log line. */
final class ConsoleView extends LinearLayout {
    private final ArrayDeque<String> lines = new ArrayDeque<>();
    private final TextView text;
    private final ScrollView scroll;
    private boolean pending;
    private long origin = SystemClock.elapsedRealtime();
    ConsoleView(Context context) {
        super(context); setOrientation(VERTICAL);
        TextView hint = new TextView(context); hint.setText("Live console · wall seconds · latest 150 lines. Full native logs are saved with each case."); addView(hint);
        text = new TextView(context); text.setTextSize(12); text.setTypeface(Typeface.MONOSPACE); text.setTextIsSelectable(true);
        scroll = new ScrollView(context); scroll.addView(text); addView(scroll, new LayoutParams(-1, -1));
    }
    synchronized void reset() { lines.clear(); origin = SystemClock.elapsedRealtime(); append("Starting workload"); }
    synchronized void append(String line) {
        if (lines.size() == 150) lines.removeFirst();
        lines.addLast(String.format(Locale.US, "%7.2f  %s", (SystemClock.elapsedRealtime() - origin) / 1000.0, line.length() > 2000 ? line.substring(0, 2000) : line));
        if (!pending) { pending = true; postDelayed(this::refresh, 200); }
    }
    private void refresh() {
        StringBuilder output = new StringBuilder();
        synchronized (this) { for (String line : lines) output.append(line).append('\n'); pending = false; }
        boolean follow = scroll.getChildAt(0).getHeight() - scroll.getHeight() - scroll.getScrollY() < 80 * getResources().getDisplayMetrics().density;
        text.setText(output.toString());
        if (follow) scroll.post(() -> scroll.fullScroll(FOCUS_DOWN));
    }
}
