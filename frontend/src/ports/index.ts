import { inject, type InjectionKey } from "vue";

/*
 * Ports: what a presentational component needs from the app that hosts it.
 *
 * Heym Work renders some of Heym's components inside its own app, where `@/services/api`, the
 * Pinia stores and the router are Work's or do not exist. Those components never import them.
 * They take data through props and get everything else from a port the host provides: Heym
 * installs its implementations in `main.ts` (`installHeymPorts`), Work installs its own.
 * `presentationalImports.test.ts` lists the components and fails when one imports them again.
 *
 * Each port is the thing the component used to import, so the code below the injection line
 * reads as before.
 */

/** Returns the host's implementation of a port; throws when the host did not provide one. */
export function usePort<T>(key: InjectionKey<T>): T {
  const port = inject(key, null);
  if (port === null) {
    throw new Error(
      `${key.description ?? "A port"} is not provided. The host app provides it (Heym: installHeymPorts() in main.ts).`,
    );
  }
  return port;
}
