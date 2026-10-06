package de.demo.mes.monitoring;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

public final class SzenarioStatus implements SzenarioStatusMXBean {

    public static final SzenarioStatus INSTANZ = new SzenarioStatus();

    public final AtomicInteger sperren = new AtomicInteger();
    public final AtomicLong heapMb = new AtomicLong();
    public final AtomicInteger dateien = new AtomicInteger();
    public final AtomicInteger timerBlockiert = new AtomicInteger();
    public final AtomicInteger langeTransaktionen = new AtomicInteger();
    public final AtomicInteger wartung = new AtomicInteger();
    public final AtomicLong offHeapMb = new AtomicLong();
    public final AtomicInteger threads = new AtomicInteger();
    public final AtomicInteger geleckteConnections = new AtomicInteger();

    private SzenarioStatus() {
    }

    public boolean inWartung() {
        return wartung.get() > 0;
    }

    @Override
    public int getGehalteneSperren() {
        return sperren.get();
    }

    @Override
    public long getGehaltenerHeapMb() {
        return heapMb.get();
    }

    @Override
    public int getOffeneDateien() {
        return dateien.get();
    }

    @Override
    public int getBlockierteTimerThreads() {
        return timerBlockiert.get();
    }

    @Override
    public int getLaufendeLangeTransaktionen() {
        return langeTransaktionen.get();
    }

    @Override
    public int getWartung() {
        return wartung.get();
    }

    @Override
    public long getGehaltenerOffHeapMb() {
        return offHeapMb.get();
    }

    @Override
    public int getZusaetzlicheThreads() {
        return threads.get();
    }

    @Override
    public int getGeleckteConnections() {
        return geleckteConnections.get();
    }
}
