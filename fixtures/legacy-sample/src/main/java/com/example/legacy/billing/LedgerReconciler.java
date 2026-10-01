package com.example.legacy.billing;

/**
 * Boundary case: exactly 400 code lines (threshold is >= 400) and complexity 51 (threshold is > 50).
 * Must be flagged as a god class.
 */
public class LedgerReconciler {
    private final String label;

    public LedgerReconciler() {
        this.label = "ledger";
    }

    public int renderSection1(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s1_1").append(x + 1);
        sb.append("s1_2").append(x + 2);
        sb.append("s1_3").append(x + 3);
        sb.append("s1_4").append(x + 4);
        sb.append("s1_5").append(x + 5);
        sb.append("s1_6").append(x + 6);
        sb.append("s1_7").append(x + 7);
        sb.append("s1_8").append(x + 8);
        sb.append("s1_9").append(x + 9);
        sb.append("s1_10").append(x + 10);
        sb.append("s1_11").append(x + 11);
        sb.append("s1_12").append(x + 12);
        sb.append("s1_13").append(x + 13);
        sb.append("s1_14").append(x + 14);
        sb.append("s1_15").append(x + 15);
        sb.append("s1_16").append(x + 16);
        sb.append("s1_17").append(x + 17);
        sb.append("s1_18").append(x + 18);
        sb.append("s1_19").append(x + 19);
        sb.append("s1_20").append(x + 20);
        sb.append("s1_21").append(x + 21);
        sb.append("s1_22").append(x + 22);
        sb.append("s1_23").append(x + 23);
        sb.append("s1_24").append(x + 24);
        sb.append("s1_25").append(x + 25);
        sb.append("s1_26").append(x + 26);
        sb.append("s1_27").append(x + 27);
        sb.append("s1_28").append(x + 28);
        sb.append("s1_29").append(x + 29);
        if (x > 1 && x < 100) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection2(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s2_1").append(x + 1);
        sb.append("s2_2").append(x + 2);
        sb.append("s2_3").append(x + 3);
        sb.append("s2_4").append(x + 4);
        sb.append("s2_5").append(x + 5);
        sb.append("s2_6").append(x + 6);
        sb.append("s2_7").append(x + 7);
        sb.append("s2_8").append(x + 8);
        sb.append("s2_9").append(x + 9);
        sb.append("s2_10").append(x + 10);
        sb.append("s2_11").append(x + 11);
        sb.append("s2_12").append(x + 12);
        sb.append("s2_13").append(x + 13);
        sb.append("s2_14").append(x + 14);
        sb.append("s2_15").append(x + 15);
        sb.append("s2_16").append(x + 16);
        sb.append("s2_17").append(x + 17);
        sb.append("s2_18").append(x + 18);
        sb.append("s2_19").append(x + 19);
        sb.append("s2_20").append(x + 20);
        sb.append("s2_21").append(x + 21);
        sb.append("s2_22").append(x + 22);
        sb.append("s2_23").append(x + 23);
        sb.append("s2_24").append(x + 24);
        sb.append("s2_25").append(x + 25);
        sb.append("s2_26").append(x + 26);
        sb.append("s2_27").append(x + 27);
        sb.append("s2_28").append(x + 28);
        sb.append("s2_29").append(x + 29);
        if (x > 2 && x < 200) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection3(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s3_1").append(x + 1);
        sb.append("s3_2").append(x + 2);
        sb.append("s3_3").append(x + 3);
        sb.append("s3_4").append(x + 4);
        sb.append("s3_5").append(x + 5);
        sb.append("s3_6").append(x + 6);
        sb.append("s3_7").append(x + 7);
        sb.append("s3_8").append(x + 8);
        sb.append("s3_9").append(x + 9);
        sb.append("s3_10").append(x + 10);
        sb.append("s3_11").append(x + 11);
        sb.append("s3_12").append(x + 12);
        sb.append("s3_13").append(x + 13);
        sb.append("s3_14").append(x + 14);
        sb.append("s3_15").append(x + 15);
        sb.append("s3_16").append(x + 16);
        sb.append("s3_17").append(x + 17);
        sb.append("s3_18").append(x + 18);
        sb.append("s3_19").append(x + 19);
        sb.append("s3_20").append(x + 20);
        sb.append("s3_21").append(x + 21);
        sb.append("s3_22").append(x + 22);
        sb.append("s3_23").append(x + 23);
        sb.append("s3_24").append(x + 24);
        sb.append("s3_25").append(x + 25);
        sb.append("s3_26").append(x + 26);
        sb.append("s3_27").append(x + 27);
        sb.append("s3_28").append(x + 28);
        sb.append("s3_29").append(x + 29);
        if (x > 3 && x < 300) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection4(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s4_1").append(x + 1);
        sb.append("s4_2").append(x + 2);
        sb.append("s4_3").append(x + 3);
        sb.append("s4_4").append(x + 4);
        sb.append("s4_5").append(x + 5);
        sb.append("s4_6").append(x + 6);
        sb.append("s4_7").append(x + 7);
        sb.append("s4_8").append(x + 8);
        sb.append("s4_9").append(x + 9);
        sb.append("s4_10").append(x + 10);
        sb.append("s4_11").append(x + 11);
        sb.append("s4_12").append(x + 12);
        sb.append("s4_13").append(x + 13);
        sb.append("s4_14").append(x + 14);
        sb.append("s4_15").append(x + 15);
        sb.append("s4_16").append(x + 16);
        sb.append("s4_17").append(x + 17);
        sb.append("s4_18").append(x + 18);
        sb.append("s4_19").append(x + 19);
        sb.append("s4_20").append(x + 20);
        sb.append("s4_21").append(x + 21);
        sb.append("s4_22").append(x + 22);
        sb.append("s4_23").append(x + 23);
        sb.append("s4_24").append(x + 24);
        sb.append("s4_25").append(x + 25);
        sb.append("s4_26").append(x + 26);
        sb.append("s4_27").append(x + 27);
        sb.append("s4_28").append(x + 28);
        if (x > 4 && x < 400) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection5(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s5_1").append(x + 1);
        sb.append("s5_2").append(x + 2);
        sb.append("s5_3").append(x + 3);
        sb.append("s5_4").append(x + 4);
        sb.append("s5_5").append(x + 5);
        sb.append("s5_6").append(x + 6);
        sb.append("s5_7").append(x + 7);
        sb.append("s5_8").append(x + 8);
        sb.append("s5_9").append(x + 9);
        sb.append("s5_10").append(x + 10);
        sb.append("s5_11").append(x + 11);
        sb.append("s5_12").append(x + 12);
        sb.append("s5_13").append(x + 13);
        sb.append("s5_14").append(x + 14);
        sb.append("s5_15").append(x + 15);
        sb.append("s5_16").append(x + 16);
        sb.append("s5_17").append(x + 17);
        sb.append("s5_18").append(x + 18);
        sb.append("s5_19").append(x + 19);
        sb.append("s5_20").append(x + 20);
        sb.append("s5_21").append(x + 21);
        sb.append("s5_22").append(x + 22);
        sb.append("s5_23").append(x + 23);
        sb.append("s5_24").append(x + 24);
        sb.append("s5_25").append(x + 25);
        sb.append("s5_26").append(x + 26);
        sb.append("s5_27").append(x + 27);
        sb.append("s5_28").append(x + 28);
        if (x > 5 && x < 500) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection6(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s6_1").append(x + 1);
        sb.append("s6_2").append(x + 2);
        sb.append("s6_3").append(x + 3);
        sb.append("s6_4").append(x + 4);
        sb.append("s6_5").append(x + 5);
        sb.append("s6_6").append(x + 6);
        sb.append("s6_7").append(x + 7);
        sb.append("s6_8").append(x + 8);
        sb.append("s6_9").append(x + 9);
        sb.append("s6_10").append(x + 10);
        sb.append("s6_11").append(x + 11);
        sb.append("s6_12").append(x + 12);
        sb.append("s6_13").append(x + 13);
        sb.append("s6_14").append(x + 14);
        sb.append("s6_15").append(x + 15);
        sb.append("s6_16").append(x + 16);
        sb.append("s6_17").append(x + 17);
        sb.append("s6_18").append(x + 18);
        sb.append("s6_19").append(x + 19);
        sb.append("s6_20").append(x + 20);
        sb.append("s6_21").append(x + 21);
        sb.append("s6_22").append(x + 22);
        sb.append("s6_23").append(x + 23);
        sb.append("s6_24").append(x + 24);
        sb.append("s6_25").append(x + 25);
        sb.append("s6_26").append(x + 26);
        sb.append("s6_27").append(x + 27);
        sb.append("s6_28").append(x + 28);
        if (x > 6 && x < 600) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection7(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s7_1").append(x + 1);
        sb.append("s7_2").append(x + 2);
        sb.append("s7_3").append(x + 3);
        sb.append("s7_4").append(x + 4);
        sb.append("s7_5").append(x + 5);
        sb.append("s7_6").append(x + 6);
        sb.append("s7_7").append(x + 7);
        sb.append("s7_8").append(x + 8);
        sb.append("s7_9").append(x + 9);
        sb.append("s7_10").append(x + 10);
        sb.append("s7_11").append(x + 11);
        sb.append("s7_12").append(x + 12);
        sb.append("s7_13").append(x + 13);
        sb.append("s7_14").append(x + 14);
        sb.append("s7_15").append(x + 15);
        sb.append("s7_16").append(x + 16);
        sb.append("s7_17").append(x + 17);
        sb.append("s7_18").append(x + 18);
        sb.append("s7_19").append(x + 19);
        sb.append("s7_20").append(x + 20);
        sb.append("s7_21").append(x + 21);
        sb.append("s7_22").append(x + 22);
        sb.append("s7_23").append(x + 23);
        sb.append("s7_24").append(x + 24);
        sb.append("s7_25").append(x + 25);
        sb.append("s7_26").append(x + 26);
        sb.append("s7_27").append(x + 27);
        sb.append("s7_28").append(x + 28);
        if (x > 7 && x < 700) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection8(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s8_1").append(x + 1);
        sb.append("s8_2").append(x + 2);
        sb.append("s8_3").append(x + 3);
        sb.append("s8_4").append(x + 4);
        sb.append("s8_5").append(x + 5);
        sb.append("s8_6").append(x + 6);
        sb.append("s8_7").append(x + 7);
        sb.append("s8_8").append(x + 8);
        sb.append("s8_9").append(x + 9);
        sb.append("s8_10").append(x + 10);
        sb.append("s8_11").append(x + 11);
        sb.append("s8_12").append(x + 12);
        sb.append("s8_13").append(x + 13);
        sb.append("s8_14").append(x + 14);
        sb.append("s8_15").append(x + 15);
        sb.append("s8_16").append(x + 16);
        sb.append("s8_17").append(x + 17);
        sb.append("s8_18").append(x + 18);
        sb.append("s8_19").append(x + 19);
        sb.append("s8_20").append(x + 20);
        sb.append("s8_21").append(x + 21);
        sb.append("s8_22").append(x + 22);
        sb.append("s8_23").append(x + 23);
        sb.append("s8_24").append(x + 24);
        sb.append("s8_25").append(x + 25);
        sb.append("s8_26").append(x + 26);
        sb.append("s8_27").append(x + 27);
        sb.append("s8_28").append(x + 28);
        if (x > 8 && x < 800) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection9(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s9_1").append(x + 1);
        sb.append("s9_2").append(x + 2);
        sb.append("s9_3").append(x + 3);
        sb.append("s9_4").append(x + 4);
        sb.append("s9_5").append(x + 5);
        sb.append("s9_6").append(x + 6);
        sb.append("s9_7").append(x + 7);
        sb.append("s9_8").append(x + 8);
        sb.append("s9_9").append(x + 9);
        sb.append("s9_10").append(x + 10);
        sb.append("s9_11").append(x + 11);
        sb.append("s9_12").append(x + 12);
        sb.append("s9_13").append(x + 13);
        sb.append("s9_14").append(x + 14);
        sb.append("s9_15").append(x + 15);
        sb.append("s9_16").append(x + 16);
        sb.append("s9_17").append(x + 17);
        sb.append("s9_18").append(x + 18);
        sb.append("s9_19").append(x + 19);
        sb.append("s9_20").append(x + 20);
        sb.append("s9_21").append(x + 21);
        sb.append("s9_22").append(x + 22);
        sb.append("s9_23").append(x + 23);
        sb.append("s9_24").append(x + 24);
        sb.append("s9_25").append(x + 25);
        sb.append("s9_26").append(x + 26);
        sb.append("s9_27").append(x + 27);
        sb.append("s9_28").append(x + 28);
        if (x > 9 && x < 900) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }

    public int renderSection10(int x) {
        StringBuilder sb = new StringBuilder();
        int r = 0;
        sb.append("s10_1").append(x + 1);
        sb.append("s10_2").append(x + 2);
        sb.append("s10_3").append(x + 3);
        sb.append("s10_4").append(x + 4);
        sb.append("s10_5").append(x + 5);
        sb.append("s10_6").append(x + 6);
        sb.append("s10_7").append(x + 7);
        sb.append("s10_8").append(x + 8);
        sb.append("s10_9").append(x + 9);
        sb.append("s10_10").append(x + 10);
        sb.append("s10_11").append(x + 11);
        sb.append("s10_12").append(x + 12);
        sb.append("s10_13").append(x + 13);
        sb.append("s10_14").append(x + 14);
        sb.append("s10_15").append(x + 15);
        sb.append("s10_16").append(x + 16);
        sb.append("s10_17").append(x + 17);
        sb.append("s10_18").append(x + 18);
        sb.append("s10_19").append(x + 19);
        sb.append("s10_20").append(x + 20);
        sb.append("s10_21").append(x + 21);
        sb.append("s10_22").append(x + 22);
        sb.append("s10_23").append(x + 23);
        sb.append("s10_24").append(x + 24);
        sb.append("s10_25").append(x + 25);
        sb.append("s10_26").append(x + 26);
        sb.append("s10_27").append(x + 27);
        sb.append("s10_28").append(x + 28);
        if (x > 10 && x < 1000) {
            r += x;
        }
        for (int i = 0; i < x; i++) {
            r += i % 3 == 0 ? 1 : 2;
        }
        return r + sb.length();
    }
}
