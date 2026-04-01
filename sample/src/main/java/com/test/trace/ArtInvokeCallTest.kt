package com.test.trace

class ArtInvokeCallTest {

    fun test() {
        ArtMethodCallTest.testStaticCall()
        ArtMethodCallTest.testStaticCallWithArg("kotlin")

        val target = ArtMethodCallTest()
        target.testInstanceCall(3)
        target.testInstanceCall(5, "overload")
        target.testCallChain()
    }
}