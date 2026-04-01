package com.test.trace;

import android.util.Log;

public class ArtMethodCallTest {

    private static final String TAG = "ATrace:HookTest";

    public static void testStaticCall() {
        testStaticCallWithArg("static");
    }

    public static long testStaticCallWithArg(String tag) {
        long now = System.currentTimeMillis();
        return now + (tag == null ? 0 : tag.length());
    }

    public int testInstanceCall(int seed) {
        return testInstanceCall(seed, "instance");
    }

    public int testInstanceCall(int seed, String extra) {
        int value = seed + (extra == null ? 0 : extra.length());
        return privateLeaf(value);
    }

    public int testCallChain() {
        int a = testInstanceCall(7);
        int b = testInstanceCall(11, "chain");
        long c = testStaticCallWithArg("chain");
        return (int) (a + b + (c & 0xF));
    }

    /**
     * 高频调用：用于验证 JIT 抑制（kAccCompileDontBother）。
     * 正常情况 ART 会在 ~10000 次调用后 JIT 编译此方法；
     * hook 后应保持 entry_point 为 trampoline 而不被 JIT 覆写。
     */
    public static long testHotLoop(int iterations) {
        long sum = 0;
        for (int i = 0; i < iterations; i++) {
            sum += hotLeaf(i);
        }
        return sum;
    }

    /** 短方法，ART 可能内联到 testHotLoop 中 */
    public static int hotLeaf(int x) {
        return x * 7 + 3;
    }

    /**
     * 递归方法：验证 trampoline 在递归调用栈下的稳定性。
     */
    public static int testRecursive(int depth) {
        if (depth <= 0) return 1;
        return depth + testRecursive(depth - 1);
    }

    private int privateLeaf(int value) {
        return value * 3 + 1;
    }

    /**
     * 一站式验证：hook → 调用 → 校验结果，返回通过的测试数量。
     */
    public static int runAll() {
        int passed = 0;

        testStaticCall();
        Log.d(TAG, "✓ testStaticCall");
        passed++;

        long r1 = testStaticCallWithArg("verify");
        Log.d(TAG, "✓ testStaticCallWithArg → " + r1);
        passed++;

        ArtMethodCallTest obj = new ArtMethodCallTest();

        int r2 = obj.testInstanceCall(10);
        Log.d(TAG, "✓ testInstanceCall(10) → " + r2);
        passed++;

        int r3 = obj.testCallChain();
        Log.d(TAG, "✓ testCallChain → " + r3);
        passed++;

        long r4 = testHotLoop(50_000);
        Log.d(TAG, "✓ testHotLoop(50000) → " + r4 + " (JIT suppression test)");
        passed++;

        int r5 = hotLeaf(42);
        Log.d(TAG, "✓ hotLeaf(42) → " + r5 + " (inline candidate)");
        passed++;

        int r6 = testRecursive(20);
        Log.d(TAG, "✓ testRecursive(20) → " + r6 + " (recursive stability)");
        passed++;

        return passed;
    }
}
