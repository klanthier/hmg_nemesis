package com.nemesis.manager;

/** Local package version and dependency comparisons. No network policy or scheduler. */
final class UpdateRule {
    private UpdateRule() {
    }

    /** Java form of native dep_spec_match: any, >=v, <=v, a-b or an exact version. */
    static boolean specMatch(String spec, String have) {
        if (spec == null || spec.length() == 0 || "any".equals(spec)) return true;
        if (have == null || !have.matches("[0-9]+(\\.[0-9]+)*")) return false;
        if (spec.startsWith(">=")) return compare(have, spec.substring(2)) >= 0;
        if (spec.startsWith("<=")) return compare(have, spec.substring(2)) <= 0;
        int dash = spec.indexOf('-');
        if (dash >= 0) {
            return compare(have, spec.substring(0, dash)) >= 0
                    && compare(have, spec.substring(dash + 1)) <= 0;
        }
        return compare(have, spec) == 0;
    }

    /** Dotted numeric compare, like native ver_cmp. */
    static int compare(String a, String b) {
        String[] x = (a == null ? "" : a.trim()).split("\\.");
        String[] y = (b == null ? "" : b.trim()).split("\\.");
        int n = Math.max(x.length, y.length);
        for (int i = 0; i < n; i++) {
            int p = i < x.length ? number(x[i]) : 0;
            int q = i < y.length ? number(y[i]) : 0;
            if (p != q) return p < q ? -1 : 1;
        }
        return 0;
    }

    private static int number(String s) {
        int v = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < '0' || c > '9') break;
            v = v * 10 + (c - '0');
        }
        return v;
    }
}
