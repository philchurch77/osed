from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from openpyxl import load_workbook

from review.models import InDepthArea, InDepthStatement


# Maps human-readable values in the Excel to InDepthStatement.StandardType keys
_STANDARD_TYPE_MAP = {
    "expected standard": InDepthStatement.StandardType.EXPECTED,
    "expected": InDepthStatement.StandardType.EXPECTED,
    "urgent improvement": InDepthStatement.StandardType.URGENT_IMPROVEMENT,
    "urgent": InDepthStatement.StandardType.URGENT_IMPROVEMENT,
    "ui": InDepthStatement.StandardType.URGENT_IMPROVEMENT,
    "needs attention": InDepthStatement.StandardType.NEEDS_ATTENTION,
    "na": InDepthStatement.StandardType.NEEDS_ATTENTION,
    "strong standard": InDepthStatement.StandardType.STRONG_STANDARD,
    "strong": InDepthStatement.StandardType.STRONG_STANDARD,
    "exceptional": InDepthStatement.StandardType.EXCEPTIONAL,
}


class Command(BaseCommand):
	help = "Import / update in-depth review statements from the Ofsted expected standard Excel file."

	def add_arguments(self, parser):
		parser.add_argument(
			"--path",
			dest="path",
			default="data/ofsted_expected_standard_review_statements.xlsx",
			help="Path to the xlsx file (default: data/ofsted_expected_standard_review_statements.xlsx)",
		)
		parser.add_argument(
			"--sheet",
			dest="sheet",
			default="Review Statements",
			help='Worksheet name (default: "Review Statements")',
		)

	def handle(self, *args, **options):
		path = Path(options["path"])
		if not path.exists():
			raise CommandError(f"File not found: {path}")

		wb = load_workbook(path, read_only=True)
		sheet_name = options["sheet"]
		ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]

		# Find the header row.
		# Supported column layouts:
		#   A: Evaluation Area | B: Statement Number | C: Statement Text
		#   Optional D: Standard Type  (Expected Standard / Needs Attention / Strong Standard)
		header_row = None
		has_standard_type_col = False
		max_row = ws.max_row or 10000
		for r in range(1, min(50, max_row) + 1):
			c1 = (ws.cell(r, 1).value or "").strip() if isinstance(ws.cell(r, 1).value, str) else ws.cell(r, 1).value
			c2 = (ws.cell(r, 2).value or "").strip() if isinstance(ws.cell(r, 2).value, str) else ws.cell(r, 2).value
			c3 = (ws.cell(r, 3).value or "").strip() if isinstance(ws.cell(r, 3).value, str) else ws.cell(r, 3).value
			c4 = (ws.cell(r, 4).value or "").strip() if isinstance(ws.cell(r, 4).value, str) else ""
			if c1 == "Evaluation Area" and c2 == "Statement Number" and c3 == "Statement Text":
				header_row = r
				has_standard_type_col = (c4.lower() == "standard type")
				break

		if header_row is None:
			raise CommandError(
				"Could not find header row with 'Evaluation Area', 'Statement Number', 'Statement Text'."
			)

		area_order: dict[str, int] = {}
		statements: list[tuple[str, int, str, str]] = []  # (area_name, num, text, standard_type)

		for r in range(header_row + 1, max_row + 1):
			area = ws.cell(r, 1).value
			num = ws.cell(r, 2).value
			text = ws.cell(r, 3).value
			standard_type_raw = ws.cell(r, 4).value if has_standard_type_col else None

			if area is None and num is None and text is None:
				continue
			if not area or not text:
				continue

			area_name = str(area).strip()
			if not area_name:
				continue

			try:
				statement_number = int(num)
			except (TypeError, ValueError):
				continue

			statement_text = str(text).strip()
			if not statement_text:
				continue

			if has_standard_type_col and standard_type_raw:
				raw_key = str(standard_type_raw).strip().lower()
				standard_type = _STANDARD_TYPE_MAP.get(raw_key, InDepthStatement.StandardType.EXPECTED)
			else:
				standard_type = InDepthStatement.StandardType.EXPECTED

			if area_name not in area_order:
				area_order[area_name] = len(area_order) + 1

			statements.append((area_name, statement_number, statement_text, standard_type))

		created_areas = 0
		updated_areas = 0
		created_statements = 0
		updated_statements = 0

		with transaction.atomic():
			areas_by_name: dict[str, InDepthArea] = {}
			for name, order in area_order.items():
				obj, created = InDepthArea.objects.update_or_create(
					name=name,
					defaults={"order": order},
				)
				areas_by_name[name] = obj
				if created:
					created_areas += 1
				else:
					updated_areas += 1

			for area_name, statement_number, statement_text, standard_type in statements:
				area_obj = areas_by_name[area_name]
				obj, created = InDepthStatement.objects.update_or_create(
					area=area_obj,
					standard_type=standard_type,
					statement_number=statement_number,
					defaults={"text": statement_text},
				)
				if created:
					created_statements += 1
				else:
					updated_statements += 1

		self.stdout.write(
			self.style.SUCCESS(
				"Imported in-depth statements: "
				f"areas created={created_areas}, areas updated={updated_areas}, "
				f"statements created={created_statements}, statements updated={updated_statements}."
			)
		)
