package de.demo.mes.rest;

import jakarta.ejb.EJBException;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.ExceptionMapper;
import jakarta.ws.rs.ext.Provider;

/**
 * TomEE bringt einen eigenen Mapper für EJBException mit, der vor einem
 * {@code ExceptionMapper<Exception>} greift. Dieser hier ist genauso spezifisch
 * und leitet an {@link FehlerAbbildung} weiter.
 */
@Provider
public class EjbFehlerAbbildung implements ExceptionMapper<EJBException> {

    private final FehlerAbbildung abbildung = new FehlerAbbildung();

    @Override
    public Response toResponse(EJBException fehler) {
        return abbildung.toResponse(fehler);
    }
}
