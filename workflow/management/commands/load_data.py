"""
python manage.py load_data

1. runs sql/schema.sql  -> drops and re-creates our 15 tables
2. loads every CSV from ./data into them, parents first

Add  --no-schema  to keep the tables and only reload rows.
"""
import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from generator import schema_spec


class Command(BaseCommand):
    help = "Create the MySQL tables from sql/schema.sql and load the generated CSV data"

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=os.path.join(settings.BASE_DIR, "data"))
        parser.add_argument("--no-schema", action="store_true", help="do not drop/create tables")

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            if not options["no_schema"]:
                self.run_schema(cursor)
            for table in schema_spec.LOAD_ORDER:
                self.load_table(cursor, table, options["data_dir"])
        self.stdout.write(self.style.SUCCESS("Database loaded."))

    def run_schema(self, cursor):
        path = os.path.join(settings.BASE_DIR, "sql", "schema.sql")
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f if not line.strip().startswith("--")]   # drop comment lines
        for statement in "".join(lines).split(";"):
            if statement.strip():
                cursor.execute(statement)
        self.stdout.write("Tables created from sql/schema.sql")

    def load_table(self, cursor, table, data_dir):
        columns = schema_spec.column_names(table)
        with open(os.path.join(data_dir, table + ".csv"), newline="", encoding="utf-8") as f:
            rows = [[(row[c] if row[c] != "" else None) for c in columns] for row in csv.DictReader(f)]
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
        for start in range(0, len(rows), 500):                   # insert in batches of 500 rows
            cursor.executemany(sql, rows[start:start + 500])
        self.stdout.write(f"  {table:22s} {len(rows):6d} rows")
