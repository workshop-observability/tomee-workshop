package de.demo.mes.rest;

import jakarta.ws.rs.ApplicationPath;
import jakarta.ws.rs.core.Application;

/** Alle Schnittstellen liegen unter {@code /mes/api}. */
@ApplicationPath("api")
public class MesApi extends Application {
}
