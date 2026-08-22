// Read-only access to planz.db (built by the Python pipeline). Every page
// and query route reads through here. The sole write surface is
// lib/mutate.ts (signals human gate + inbox files, docs D31); plan tables
// are never written by the app — re-planning happens through the pipeline.
import Database from "better-sqlite3";
import path from "path";

let db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (!db) {
    const file =
      process.env.PLANZ_DB ?? path.join(process.cwd(), "..", "planz.db");
    db = new Database(file, { readonly: true, fileMustExist: true });
  }
  return db;
}

export function rows<T = Record<string, unknown>>(
  sql: string,
  ...args: unknown[]
): T[] {
  return getDb().prepare(sql).all(...args) as T[];
}
