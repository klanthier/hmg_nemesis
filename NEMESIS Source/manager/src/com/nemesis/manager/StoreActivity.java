package com.nemesis.manager;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Package Store. Started by a type=list stick (store_mode=usb) or from the main screen.
 *  Exported through the stick flow, so extras never name a path: the list is read
 *  from the mounted stick with usb-info. */
public class StoreActivity extends Activity {
    private static final int GREEN = 0xFF6FBF73;
    private static final int YELLOW = 0xFFE3C565;
    private static final int RED = 0xFFD9685F;
    private static final int PLAIN = 0xFFB6C1C8;

    private boolean usbOk;
    private String usbRoot;
    private List<StoreList.Entry> all = new ArrayList<StoreList.Entry>();
    private List<StoreList.Entry> shown = new ArrayList<StoreList.Entry>();
    private boolean showAll;
    private boolean byDate = true;
    private boolean ascending;
    private int loadGen;
    /** The stick's one package update check, spent on the first load. */
    private boolean usbLaunchCheck;
    private final RowAdapter adapter = new RowAdapter();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Ui.ensureWatchdog();
        if (!Ui.setLayout(this, R.layout.activity_store)) {
            Ui.close(this);
            return;
        }
        Ui.bindTitle(this, R.string.store);
        usbLaunchCheck = "usb".equals(getIntent().getStringExtra("store_mode"));
        click(R.id.btn_updates, new Runnable() {
            public void run() {
                startActivity(new Intent(StoreActivity.this, UpdatesActivity.class));
            }
        });
        ListView lv = (ListView) findViewById(R.id.list);
        lv.setAdapter(adapter);
        lv.setEmptyView(findViewById(R.id.empty));
        lv.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            public void onItemClick(AdapterView<?> p, View v, int pos, long id) {
                if (pos < shown.size()) open(shown.get(pos));
            }
        });
        click(R.id.sort_field, new Runnable() {
            public void run() {
                byDate = !byDate;
                refresh();
            }
        });
        click(R.id.sort_dir, new Runnable() {
            public void run() {
                ascending = !ascending;
                refresh();
            }
        });
        click(R.id.show_all, new Runnable() {
            public void run() {
                showAll = !showAll;
                refresh();
            }
        });
        ((EditText) findViewById(R.id.search)).addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void onTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void afterTextChanged(Editable s) {
                refresh();
            }
        });
    }

    private void click(int id, final Runnable r) {
        findViewById(id).setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                r.run();
            }
        });
    }

    /** Back from an install or uninstall popup too: installed state changed. */
    @Override
    protected void onResume() {
        super.onResume();
        if (findViewById(R.id.search) != null) load();
    }

    /** Load package metadata only from the mounted USB drive. */
    private void load() {
        final int gen = ++loadGen;
        new Thread(new Runnable() {
            public void run() {
                Map<String, String> info = Cli.fields(Cli.run("usb-info"));
                final String root = info.get("root");
                final boolean hasList = "list".equals(info.get("type"))
                        && root != null && root.length() > 0;
                final List<StoreList.Entry> rows = hasList
                        ? StoreList.parseList(Cli.run("usb-info", "--list"))
                        : new ArrayList<StoreList.Entry>();
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (gen != loadGen || isFinishing()) return;
                        usbOk = hasList;
                        usbRoot = root;
                        all = rows;
                        refresh();
                    }
                });
                for (int k = 0; k < rows.size() && gen == loadGen; k++) {
                    StoreList.Entry e = rows.get(k);
                    try {
                        resolveUsb(e, root);
                    } catch (Throwable t) {
                        CrashLog.note("update.log", "USB descriptor " + e.name + ": " + t);
                    }
                    runOnUiThread(new Runnable() {
                        public void run() {
                            if (gen == loadGen && !isFinishing()) refresh();
                        }
                    });
                }
                final int count = StoreList.updates(rows).size();
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (gen != loadGen || isFinishing()) return;
                        TextView badge = (TextView) findViewById(R.id.updates_badge);
                        badge.setText(String.valueOf(count));
                        badge.setVisibility(count > 0 ? View.VISIBLE : View.GONE);
                        if (usbLaunchCheck && usbOk && count > 0) PkgUpdates.popup(StoreActivity.this, count);
                        usbLaunchCheck = false;
                    }
                });
            }
        }).start();
    }

    static void resolveUsb(StoreList.Entry e, String root) {
        if (root == null || root.length() == 0 || !StoreList.relOk(e.path)) {
            e.localZip = "";
            e.compat = StoreList.NONE;
            return;
        }
        e.localZip = root + "/" + e.path;
        if (!UsbPaths.contains(root, e.localZip)) {
            e.localZip = "";
            e.compat = StoreList.NONE;
            return;
        }
        Cli.Result r = Cli.exec("pkg-info", e.localZip);
        if (r.rc != 0) {
            e.localZip = "";
            e.compat = StoreList.NONE;
            return;
        }
        Map<String, String> m = Cli.fields(r.out);
        e.id = or(m.get("id"), "");
        e.version = or(m.get("package-version"), "");
        e.isInstalled = "1".equals(m.get("installed"));
        e.installed = or(m.get("installed-version"), "");
        e.locked = "1".equals(m.get("locked"));
        e.compat = StoreList.compatOf(m.get("compat"));
        e.legacy = StoreList.isLegacy(m.get("version"));
        e.detailedDesc = PackageActivity.unescape(or(m.get("detailed-desc"), ""));
        e.depends = or(m.get("depends"), "");
        e.reasons = StoreList.reasons(r.out);
    }

    private static String or(String v, String d) {
        return v == null ? d : v;
    }

    private void refresh() {
        String q = ((EditText) findViewById(R.id.search)).getText().toString();
        shown = StoreList.view(all, q, showAll, byDate, ascending);
        adapter.notifyDataSetChanged();
        ((TextView) findViewById(R.id.empty)).setText(usbOk ? R.string.empty_store : R.string.empty_store_usb);
        ((Button) findViewById(R.id.sort_field)).setText(byDate ? R.string.sort_date : R.string.sort_name);
        ((Button) findViewById(R.id.sort_dir)).setText(ascending ? "↑" : "↓");
        Button more = (Button) findViewById(R.id.show_all);
        int hidden = StoreList.hiddenCount(all);
        more.setVisibility(hidden > 0 ? View.VISIBLE : View.GONE);
        more.setText(showAll ? getString(R.string.show_full_only)
                : getString(R.string.show_all).replace("%d", String.valueOf(hidden)));
    }

    private void open(StoreList.Entry e) {
        Intent i = new Intent(this, StoreDetailActivity.class);
        i.putExtra("store_id", e.id);
        i.putExtra("store_name", e.name);
        i.putExtra("store_short", e.shortDesc);
        i.putExtra("store_published", e.published);
        i.putExtra("store_root", usbRoot);
        i.putExtra("store_path", e.path);
        startActivity(i);
    }

    private final class RowAdapter extends BaseAdapter {
        public int getCount() {
            return shown.size();
        }

        public Object getItem(int pos) {
            return shown.get(pos);
        }

        public long getItemId(int pos) {
            return pos;
        }

        public View getView(int pos, View convert, ViewGroup parent) {
            View v = convert != null ? convert
                    : LayoutInflater.from(StoreActivity.this).inflate(R.layout.store_row, parent, false);
            StoreList.Entry e = shown.get(pos);
            TextView t = (TextView) v.findViewById(R.id.row_title);
            TextView s = (TextView) v.findViewById(R.id.row_summary);
            t.setText(e.name);
            v.findViewById(R.id.row_installed_col).setVisibility(e.isInstalled ? View.VISIBLE : View.GONE);
            ((TextView) v.findViewById(R.id.row_installed_ver)).setText(e.installed);
            boolean newer = e.isInstalled && UpdateRule.compare(e.version, e.installed) > 0;
            v.findViewById(R.id.row_update_col).setVisibility(newer ? View.VISIBLE : View.GONE);
            ((TextView) v.findViewById(R.id.row_update_ver)).setText(e.version);
            int shade = StoreList.shade(e);
            t.setTextColor(shade == StoreList.FULL ? GREEN : shade == StoreList.PARTIAL ? YELLOW
                    : shade == StoreList.NONE ? RED : PLAIN);
            s.setText(e.legacy ? getString(R.string.legacy_short) + " • " + e.shortDesc : e.shortDesc);
            return v;
        }
    }
}
