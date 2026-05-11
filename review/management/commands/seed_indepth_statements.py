from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from openpyxl import load_workbook

from review.models import InDepthArea, InDepthStatement


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

		# Find the header row (expects columns: Evaluation Area | Statement Number | Statement Text)
		header_row = None
		for r in range(1, min(50, ws.max_row) + 1):
			c1 = (ws.cell(r, 1).value or "").strip() if isinstance(ws.cell(r, 1).value, str) else ws.cell(r, 1).value
			c2 = (ws.cell(r, 2).value or "").strip() if isinstance(ws.cell(r, 2).value, str) else ws.cell(r, 2).value
			c3 = (ws.cell(r, 3).value or "").strip() if isinstance(ws.cell(r, 3).value, str) else ws.cell(r, 3).value
			if c1 == "Evaluation Area" and c2 == "Statement Number" and c3 == "Statement Text":
				header_row = r
				break

		if header_row is None:
			raise CommandError(
				"Could not find header row with 'Evaluation Area', 'Statement Number', 'Statement Text'."
			)

		area_order: dict[str, int] = {}
		statements: list[tuple[str, int, str]] = []

		for r in range(header_row + 1, ws.max_row + 1):
			area = ws.cell(r, 1).value
			num = ws.cell(r, 2).value
			text = ws.cell(r, 3).value

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

			if area_name not in area_order:
				area_order[area_name] = len(area_order) + 1
			statements.append((area_name, statement_number, statement_text))

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

			for area_name, statement_number, statement_text in statements:
				area_obj = areas_by_name[area_name]
				obj, created = InDepthStatement.objects.update_or_create(
					area=area_obj,
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
