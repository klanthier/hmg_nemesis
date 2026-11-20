package com.nemesis.manager;

import android.content.Context;
import android.content.Intent;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Package updates and dependencies supplied by the mounted USB drive. */
final class PkgUpdates {
    static final class Found {
        List<StoreList.Entry> updates = new ArrayList<StoreList.Entry>();
    }

    private PkgUpdates() {
    }

    /** The stick's rows, resolved. Empty when it has no list. */
    static List<StoreList.Entry> usbRows() {
        Map<String, String> info = Cli.fields(Cli.run("usb-info"));
        if (!"list".equals(info.get("type")) || info.get("root") == null)
            return new ArrayList<StoreList.Entry>();
        List<StoreList.Entry> rows = StoreList.parseList(Cli.run("usb-info", "--list"));
        for (int i = 0; i < rows.size(); i++) StoreActivity.resolveUsb(rows.get(i), info.get("root"));
        return rows;
    }

    static Found find(Context c) {
        Found f = new Found();
        f.updates = StoreList.updates(usbRows());
        return f;
    }

    static void popup(Context c, int count) {
        Intent i = new Intent(c, DialogActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        i.putExtra("nemesis_mode", "pkg_updates");
        i.putExtra("nemesis_count", count);
        c.startActivity(i);
    }

    /** Resolve dependencies from installed packages and the USB list only. */
    static DepPlan.Source source(final Context c) {
        return new DepPlan.Source() {
            private List<StoreList.Entry> usb;

            public String installed(String id) {
                Map<String, String> m = Cli.fields(Cli.run("pkg-info", id));
                if (!"1".equals(m.get("installed"))) return null;
                String v = m.get("installed-version");
                return v == null ? "" : v;
            }

            public StoreList.Entry find(String id, String spec) {
                if (usb == null) usb = usbRows();
                StoreList.Entry best = null;
                for (int i = 0; i < usb.size(); i++) {
                    StoreList.Entry e = usb.get(i);
                    if (!id.equals(e.id) || !usable(e, spec)) continue;
                    if (best == null || UpdateRule.compare(e.version, best.version) > 0) best = e;
                }
                return best;
            }
        };
    }

    private static boolean usable(StoreList.Entry e, String spec) {
        return e.compat != StoreList.NONE && e.compat != StoreList.UNKNOWN
                && UpdateRule.specMatch(spec, e.version);
    }
}
