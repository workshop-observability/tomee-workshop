package de.demo.mes.monitoring;

import jakarta.annotation.Resource;
import jakarta.interceptor.AroundInvoke;
import jakarta.interceptor.InvocationContext;
import jakarta.transaction.Status;
import jakarta.transaction.Synchronization;
import jakarta.transaction.TransactionSynchronizationRegistry;

/**
 * EJB-Interceptor: meldet jede containergesteuerte Transaktion einmalig bei
 * {@link Transaktionen} an und über eine Synchronization wieder ab.
 */
public class TransaktionsUeberwachung {

    private static final String SCHLUESSEL = TransaktionsUeberwachung.class.getName();

    @Resource
    private TransactionSynchronizationRegistry registry;

    @AroundInvoke
    public Object ueberwachen(InvocationContext ctx) throws Exception {
        anmelden(registry, ctx.getTarget().getClass().getSimpleName() + "." + ctx.getMethod().getName());
        return ctx.proceed();
    }

    /** Auch für Bean-Managed Transactions nach {@code UserTransaction.begin()} nutzbar. */
    public static void anmelden(TransactionSynchronizationRegistry registry, String wo) {
        if (registry == null || registry.getTransactionStatus() != Status.STATUS_ACTIVE
                || registry.getResource(SCHLUESSEL) != null) {
            return;
        }
        long id = Transaktionen.INSTANZ.begonnen(wo);
        registry.putResource(SCHLUESSEL, id);
        registry.registerInterposedSynchronization(new Synchronization() {
            @Override
            public void beforeCompletion() {
            }

            @Override
            public void afterCompletion(int status) {
                Transaktionen.INSTANZ.beendet(id, status);
            }
        });
    }
}
