# Fixture: `fixtures/legacy-sample`

A small, deliberately bad Java 8 app (18 main classes, 4 package-modules, 1,227 LOC) that is the
**test oracle** for the analyzer. `fixtures/expected.json` lists exactly what the analyzer must find.
It does not compile against real OFBiz; `Delegator`, `EntityQuery` and `GenericValue` are minimal stubs.

## Layout

| Module (package) | Classes | Tests | Role |
|---|---|---|---|
| `order` | OrderServices, OrderReadHelper, ShoppingCart, Order, OrderItem, OrderStatus | none | the risky core |
| `billing` | InvoiceService, PaymentCalculator, InvoiceItem, BillingException | yes (2 classes) | raw JDBC |
| `party` | PartyService, PartyController, PartyLegacyHelper, Party | yes (1 class) | namespace mix |
| `common` | Delegator, EntityQuery, GenericValue, StringUtil | none | OFBiz-style stubs, util |

Also: `src/main/resources/servicedef/services.xml` (5 services), `src/main/groovy/.../CheckOrderFraud.groovy`,
`pom.xml` and `gradle/libs.versions.toml`.

## Smells and the real OFBiz pattern each stands in for

| Smell | Where | Real OFBiz pattern |
|---|---|---|
| God class | `OrderServices` (793 LOC, complexity 229, 16 similar workflow methods) | `OrderServices.java` 7,516 LOC; `ShoppingCart.java` 6,416 |
| Highly coupled service | `OrderReadHelper` (fan-in 5, fan-out 10), creating cycles order↔party and order↔billing | order/party/accounting components calling each other's helpers |
| JDBC in business logic | `InvoiceService` (5 instances) | hand-written SQL in older helpers |
| Entity-engine coupling | 55 instances in `OrderServices`, `OrderReadHelper`, `PartyService` | 402 `EntityQuery` uses in `applications/order` alone |
| Missing tests | `order`, `common` | 0 tests in order/product/party/accounting |
| javax/jakarta mix | `party`: `PartyController` (jakarta) next to `PartyLegacyHelper` (javax) | 139 javax vs 272 jakarta files, mid-migration |
| EJB marker | `javax.ejb.Stateless` on `OrderServices` | EJB-era design |
| Logic outside Java | `services.xml` + Groovy script | 85 `services*.xml` and 450 Groovy files |
| Outdated dependencies | 4 in `pom.xml`, 4 in the TOML; `slf4j-api` and `junit` are current (negative cases) | `dependencies.gradle` / version catalog |

## Traps (things the analyzer must NOT count)
- `PaymentCalculator`: `EntityQuery.use(` / `prepareStatement(` in a Javadoc comment and a string literal are not DB coupling; the Javadoc mention of `InvoiceService` is not a dependency. This is why tree-sitter parsing is required, not grep.
- `javax.sql.DataSource` is a JDK package, not a legacy marker.
- `StringUtil`/`GenericValue`: high fan-in, zero fan-out, not "highly coupled". `OrderServices`: fan-out 13 but fan-in 0, so god class but not "highly coupled".
- Stub declarations of `create`/`findOne`/`use` are not DB-coupling instances.

## How expected.json was produced
Rules are written in its `rules` block (LOC, fan-in/out, complexity, thresholds, what counts as a DB instance or marker).
Values were generated from the sources by a throwaway script that is not part of the repo and then spot-checked by hand
(e.g. entity hits 55 = 16 methods × 3 in `OrderServices` + 3 in `PartyService` + 4 in `OrderReadHelper`).
Complexity is an approximation of cyclomatic complexity, per the stated rule. The thresholds in `rules` (god class, coupling,
bands) must move into `config/assumptions.yaml` in Phase 2.
`min_current_major` for dependencies is a conservative lower bound chosen for the fixture; the analyzer's bundled table must be at least as high.
