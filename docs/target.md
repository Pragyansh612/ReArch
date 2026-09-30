# Demo target selection

Evaluated 2026-09-30 by shallow-cloning each candidate into `targets/` (git-ignored).
All numbers below were measured with `find`/`wc`/`grep`, not estimated.

## Candidates

| | mybatis/jpetstore-6 @ 1ffdf1e | Apache OFBiz framework @ c572aa78 |
|---|---|---|
| Java files | 46 | 1,259 |
| Main Java LOC | 3,865 | 355,174 |
| Test files / `@Test` count | 20 / 108 | 123 / 880 |
| Build | Maven (`pom.xml`, single module) | Gradle (`build.gradle`, version catalog, multi-component) |
| Java version | 8 | 17 |
| Web stack | Spring MVC 5.3.39 (EOL), JSP, `javax.servlet` | Own MVC/"screens" + Tomcat, Freemarker, Groovy |
| Data access | MyBatis mappers (no direct JDBC) | Entity engine (`delegator`/`EntityQuery`); logic also in XML services and Groovy |
| Namespace migration | 11 `javax.*` imports, 0 `jakarta.*` in Java | 139 files `javax.*`, 272 `jakarta.*` (mid-migration) |
| Logical modules | ~4 packages (domain, mapper, service, web) | 8+ components under `applications/` |
| Largest class | `Order.java` 684 LOC | `OrderServices.java` 7,516 LOC; `ShoppingCart.java` 6,416 |

### OFBiz bounded subset (Java only, main)

| Component | Files | LOC | Tests |
|---|---|---|---|
| order | 33 | 40,103 | 0 |
| product | 71 | 32,123 | 0 |
| content | 55 | 21,259 | 1 |
| accounting | 17 | 15,285 | 0 |
| manufacturing | 13 | 9,386 | 0 |
| party | 11 | 7,876 | 0 |
| workeffort | 12 | 5,582 | 0 |
| humanres | 1 | 256 | 0 |

order + product + party + accounting = 132 files, about 95k LOC.

## Recommendation: OFBiz, bounded to order + product + party + accounting

**Why not JPetStore as the primary target**
- Too small and already reasonably clean: MyBatis (no JDBC in business logic), tests for every layer,
  only ~4 packages. A modernization advisor needs modules to *differentiate*; here almost everything scores
  the same, so the heatmap, strategy choice and wave ordering would be uninteresting.
- Its legacy signals are version-based (Java 8, Spring 5.3 EOL, `javax.servlet`), which is real but
  thin for a business case.

**Why OFBiz**
- Real ERP domain (orders, invoicing, catalog, parties) that a Japanese enterprise client would recognise.
- Genuine structural debt the analyzer can measure: multi-thousand-line god classes, very low test
  presence in applications (0 tests in order/product/party/accounting), heavy cross-component coupling.
- Enough modules (4-8) to make heatmap, strategy differences, dependency-ordered waves and strangler
  extraction meaningful.

**Risks to accept (and state in the README)**
1. Not "old Java": it targets Java 17 and is mid-way through javax to jakarta. Legacy evidence is
   structural (size, coupling, tests), not version age. Dependency-age checks still apply to Gradle deps.
2. **Blind spot:** much business logic lives in XML service definitions (85 `services*.xml`) and Groovy
   (450 files). A Java-only analyzer under-counts; say so explicitly as a limitation.
3. **Gradle, not Maven:** `pom.xml` parsing alone will not cover it. Phase 2 needs a small parser for
   `gradle/libs.versions.toml` (and keep pom parsing for JPetStore and the fixture).
4. Size: must analyze the subset only, not all 355k LOC, to keep analysis fast and the graph readable.

**Keep JPetStore as a secondary smoke-test target**: it runs the Maven path end to end in seconds.

Decision status: recommendation only; awaiting user confirmation.
