from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from review.models import ComplaintTheme, OperationsMetric, OperationsMetricBand, TrustCategory
from review.operations import (
    RULE_BAND_CHOICE,
    RULE_COMPLAINTS_TREND,
    RULE_COUNT_THRESHOLD,
    RULE_GRANT_PUBLICATION,
    RULE_NUMERIC_RANGE,
    RULE_STATUTORY_DATES,
    RULE_VS_COMPARATOR_PCT,
    RULE_VS_COMPARATOR_POINTS,
)

BENCHMARKED = OperationsMetric.Evidence.BENCHMARKED
JUDGEMENT = OperationsMetric.Evidence.JUDGEMENT
TERMLY = OperationsMetric.Cycle.TERMLY
ANNUAL = OperationsMetric.Cycle.ANNUAL


# Twelve RAG-rated metrics across five domains. The predominant complaint theme
# is NOT a metric row: it is a note attached to the complaints tile.
#
# `evidence` is a label, not logic. The source document names Finance/ICFP and
# HR absence as genuine national benchmarks and the IT Digital Standards
# self-assessment as closer to a judgement; the rest are a best guess and are
# flagged for the client to correct.
METRICS: list[dict] = [
    # ---------------------------------------------------------- Finance & ICFP
    {
        "domain": "finance-icfp",
        "key": "in-year-budget-position",
        "name": "In-year budget position (surplus/deficit vs plan)",
        "benchmark_source": "DfE (any surplus = low risk); Trust reserves policy",
        "rule": RULE_BAND_CHOICE,
        "evidence": BENCHMARKED,
        "order": 10,
        "bands": [{
            "green_descriptor": "On/ahead of budget",
            "amber_descriptor": "Behind budget, within an approved recovery plan",
            "red_descriptor": "In deficit with no approved plan, or adverse variance >2% of income",
        }],
    },
    {
        "domain": "finance-icfp",
        "key": "curriculum-bonus-deficit",
        "name": "Curriculum bonus/(deficit) — leading indicator",
        "benchmark_source": "School's own ICFP tool (via IMP) run against funded entitlement",
        "rule": RULE_BAND_CHOICE,
        "evidence": BENCHMARKED,
        "order": 20,
        "bands": [{
            "green_descriptor": "Bonus, or deficit within 1% of entitlement",
            "amber_descriptor": "Deficit of 1–3%, or worsening trend",
            "red_descriptor": "Deficit >3%, or worsening month-on-month",
        }],
    },
    {
        "domain": "finance-icfp",
        "key": "staff-costs-pct-income",
        "name": "Staff costs as % of Total Revenue Income",
        "benchmark_source": "ASOT/ISBL threshold; cross-check via DfE FBIT",
        "rule": RULE_NUMERIC_RANGE,
        "evidence": BENCHMARKED,
        "value_label": "% of total revenue income",
        "order": 30,
        # SECONDARY only. There is deliberately NO primary band and no
        # all-phases fallback: the ISBL threshold data is a paid product the
        # Trust does not hold, so Primary stays Blue for the foreseeable future.
        # That is the expected state, not a placeholder.
        "bands": [{
            "phase": "SECONDARY",
            "green_min": 73, "green_max": 76,
            "amber_min": 69, "amber_max": 80,
            "green_descriptor": "73–76%",
            "amber_descriptor": "Up to 4 points outside the green band",
            "red_descriptor": "More than 4 points outside the green band",
            "comparator_year": "2025",
            "comparator_source": "Stowupland 2025 (secondary illustration)",
        }],
    },
    {
        "domain": "finance-icfp",
        "key": "revenue-reserves-pct-gag",
        "name": "Revenue reserves as % of GAG",
        "benchmark_source": "ISBL green band (0–5% of income); Trust reserves policy (5% of GAG)",
        "rule": RULE_NUMERIC_RANGE,
        "evidence": BENCHMARKED,
        "value_label": "% of GAG",
        "order": 40,
        "bands": [{
            "green_min": 3, "green_max": 8,
            "amber_min": 0, "amber_max": 15,
            "green_descriptor": "3–8% (around Trust policy)",
            "amber_descriptor": "0–3%, or 8–15%",
            "red_descriptor": "Negative, or >15% unexplained",
        }],
    },
    # -------------------------------------------------------- HR & Workforce
    {
        "domain": "hr-workforce",
        "key": "staff-sickness-absence",
        "name": "Staff sickness absence",
        "benchmark_source": 'DfE "School workforce in England", published annually',
        "rule": RULE_VS_COMPARATOR_PCT,
        "evidence": BENCHMARKED,
        "value_label": "average days lost per teacher",
        "order": 10,
        "bands": [{
            "comparator_value": 8,
            "comparator_year": "2024/25",
            "comparator_source": 'DfE "School workforce in England"',
            "amber_tolerance": 20,
            "green_descriptor": "At/below the current national figure",
            "amber_descriptor": "Up to 20% above",
            "red_descriptor": "More than 20% above, or rising for 2+ terms",
        }],
    },
    {
        "domain": "hr-workforce",
        "key": "staff-turnover-vacancy",
        "name": "Staff turnover / vacancy rate",
        "benchmark_source": "DfE School Workforce Census, national rates by phase",
        "rule": RULE_VS_COMPARATOR_POINTS,
        "evidence": BENCHMARKED,
        "value_label": "% turnover",
        "order": 20,
        # Phase-specific national rates. Both are placeholders until the finance
        # team supplies the census figures.
        "bands": [
            {
                "phase": "SECONDARY",
                "comparator_value": 12, "comparator_year": "2024/25",
                "comparator_source": "DfE School Workforce Census (secondary)",
                "amber_tolerance": 5,
                "green_descriptor": "In line with/below the national rate for phase",
                "amber_descriptor": "Up to 5 points above",
                "red_descriptor": "More than 5 points above, or a core-subject/class-teacher vacancy unfilled a full term",
            },
            {
                "phase": "PRIMARY",
                "comparator_value": 11, "comparator_year": "2024/25",
                "comparator_source": "DfE School Workforce Census (primary)",
                "amber_tolerance": 5,
                "green_descriptor": "In line with/below the national rate for phase",
                "amber_descriptor": "Up to 5 points above",
                "red_descriptor": "More than 5 points above, or a class-teacher vacancy unfilled a full term",
            },
        ],
    },
    # --------------------------------------------------- Estates & Operations
    {
        "domain": "estates-operations",
        "key": "estates-condition-grade",
        "name": "Estates condition grade",
        "benchmark_source": "DfE Condition Data Collection (CDC), via Manage Your Education Estate",
        "rule": RULE_BAND_CHOICE,
        "evidence": BENCHMARKED,
        "cycle": ANNUAL,
        "order": 10,
        "bands": [{
            "green_descriptor": "Grade A/B (good/satisfactory)",
            "amber_descriptor": "Grade C on non-critical elements, costed plan in place",
            "red_descriptor": "Grade D on any element, or a growing backlog",
        }],
    },
    {
        "domain": "estates-operations",
        "key": "statutory-compliance",
        "name": "Statutory compliance",
        "benchmark_source": "Statutory requirement — tracked, not benchmarked",
        "rule": RULE_STATUTORY_DATES,
        "evidence": BENCHMARKED,
        "help_text": (
            "Computed from the five statutory due dates (fire risk assessment, "
            "legionella, asbestos, gas/electrical safety, EPC). Never entered."
        ),
        "order": 20,
        "bands": [{
            "green_descriptor": "100% in date",
            "amber_descriptor": "One item overdue less than a month, action plan in place",
            "red_descriptor": "Any item overdue more than a month, or no action plan",
        }],
    },
    # --------------------------------------------------------------------- IT
    {
        "domain": "it",
        "key": "digital-technology-standards",
        "name": "DfE Digital and Technology Standards self-assessment",
        "benchmark_source": (
            "DfE's six core standards — broadband, wireless network, network "
            "switching, cyber security, filtering & monitoring, digital "
            "leadership & governance; all schools expected to meet by 2030"
        ),
        "rule": RULE_COUNT_THRESHOLD,
        "evidence": JUDGEMENT,
        "cycle": ANNUAL,
        "value_label": "standards met (of 6)",
        "order": 10,
        "bands": [{
            "green_min": 6, "amber_min": 4,
            "green_descriptor": "Meeting all six",
            "amber_descriptor": "Meeting four or five, costed roadmap for the rest",
            "red_descriptor": "Meeting fewer than four, or no roadmap",
        }],
    },
    {
        "domain": "it",
        "key": "cyber-essentials",
        "name": "Cyber Essentials / Cyber Essentials Plus certification",
        "benchmark_source": "Cyber Essentials scheme",
        "rule": RULE_BAND_CHOICE,
        "evidence": BENCHMARKED,
        "order": 20,
        "bands": [{
            "green_descriptor": "Certified and in date",
            "amber_descriptor": "Lapsed less than 3 months, renewal booked",
            "red_descriptor": "Not certified, or lapsed more than 3 months",
        }],
    },
    # ----------------------------------------------- Governance & Compliance
    {
        "domain": "governance-compliance",
        "key": "complaints-stage-2",
        "name": "Formal complaints reaching Stage 2+",
        "benchmark_source": "No national comparator exists; RAG is based on the school's own trend",
        "rule": RULE_COMPLAINTS_TREND,
        "evidence": JUDGEMENT,
        "value_label": "complaints reaching Stage 2+ this term",
        "help_text": (
            "By trend, not volume. The RAG is computed from this school's own "
            "history, so the first term of the pilot shows Blue, not Green."
        ),
        "order": 10,
        "bands": [{
            "green_descriptor": "Flat or falling on the previous term (including zero)",
            "amber_descriptor": "Rising for the first time this term",
            "red_descriptor": "Rising for two or more consecutive terms, or a marked step-change in a single term",
            "step_change": 3,
        }],
    },
    {
        "domain": "governance-compliance",
        "key": "grant-publication",
        "name": "Ring-fenced grant strategy/report publication",
        "benchmark_source": (
            "DfE conditions of grant, checked annually: Pupil Premium (all "
            "schools), Inclusive Mainstream Fund (all mainstream), PE and Sport "
            "Premium (primary only)"
        ),
        "rule": RULE_GRANT_PUBLICATION,
        "evidence": BENCHMARKED,
        "cycle": ANNUAL,
        "help_text": "The applicable set follows from the school's phase and type.",
        "order": 20,
        "bands": [{
            "green_descriptor": "All applicable strategies/reports published and on file, on time",
            "amber_descriptor": "Drafted but not published, deadline approaching within the term",
            "red_descriptor": "Deadline missed for any applicable grant",
        }],
    },
]

# The client has not agreed a theme taxonomy; these are the source document's
# examples and the list is admin-editable.
COMPLAINT_THEMES = ["SEND", "Behaviour", "Communication", "Admissions"]


class Command(BaseCommand):
    help = (
        "Seed the Operations & Resources metric catalogue and their bands. "
        "Idempotent — safe to run on every deploy. Does NOT switch anything on: "
        "every metric stays hidden until someone turns it on per school."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Re-apply the seed values to metrics, bands and complaint themes "
                "that already exist, discarding any admin edits. Off by default "
                "so a deploy cannot silently revert a correction."
            ),
        )

    def handle(self, *args, **options):
        # Seed values are applied on creation. On a row that already exists they
        # are left alone unless --force, because these fields are admin-editable
        # and a deploy that overwrites them silently undoes the client's own
        # corrections -- step_change and the turnover comparators exist
        # specifically so they can be fixed without a deploy.
        force: bool = options["force"]
        missing_domains: list[str] = []
        created = updated = 0

        with transaction.atomic():
            for spec in METRICS:
                domain = TrustCategory.objects.filter(domain_key=spec["domain"]).first()
                if domain is None:
                    missing_domains.append(spec["domain"])
                    continue

                metric_values = {
                    "domain": domain,
                    "name": spec["name"],
                    "benchmark_source": spec.get("benchmark_source", ""),
                    "rule": spec["rule"],
                    "evidence": spec.get("evidence", JUDGEMENT),
                    "cycle": spec.get("cycle", TERMLY),
                    "value_label": spec.get("value_label", ""),
                    "help_text": spec.get("help_text", ""),
                    "order": spec["order"],
                }
                metric, was_created = OperationsMetric.objects.update_or_create(
                    key=spec["key"],
                    defaults=metric_values if force else {},
                    create_defaults=metric_values,
                )
                created += int(was_created)
                updated += int(not was_created)

                wanted_phases = {b.get("phase", "") for b in spec["bands"]}
                for band in spec["bands"]:
                    band_values = {
                        "green_descriptor": band.get("green_descriptor", ""),
                        "amber_descriptor": band.get("amber_descriptor", ""),
                        "red_descriptor": band.get("red_descriptor", ""),
                        "green_min": band.get("green_min"),
                        "green_max": band.get("green_max"),
                        "amber_min": band.get("amber_min"),
                        "amber_max": band.get("amber_max"),
                        "amber_tolerance": band.get("amber_tolerance"),
                        "comparator_value": band.get("comparator_value"),
                        "comparator_year": band.get("comparator_year", ""),
                        "comparator_source": band.get("comparator_source", ""),
                        "step_change": band.get("step_change", 3),
                    }
                    OperationsMetricBand.objects.update_or_create(
                        metric=metric,
                        phase=band.get("phase", ""),
                        defaults=band_values if force else {},
                        create_defaults=band_values,
                    )
                # Drop bands that are no longer in the seed, so removing a phase
                # band here actually removes it (this is how Primary staff costs
                # stays Blue).
                metric.bands.exclude(phase__in=wanted_phases).delete()

            for order, name in enumerate(COMPLAINT_THEMES, start=1):
                theme_values = {"order": order * 10, "is_active": True}
                ComplaintTheme.objects.update_or_create(
                    name=name,
                    defaults=theme_values if force else {},
                    create_defaults=theme_values,
                )

        total = OperationsMetric.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Operations metrics seeded. Created: {created}, updated: {updated}, "
                f"total: {total}. All remain hidden until switched on per school."
            )
        )
        for key in missing_domains:
            self.stdout.write(
                self.style.WARNING(
                    f'No Operations & Resources domain "{key}" — metric skipped. '
                    "Run seed_trust_categories first."
                )
            )
