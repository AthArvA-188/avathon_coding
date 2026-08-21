// Read-only access to planz.db (built by the Python pipeline).
// The app never writes: re-planning happens by re-running the pipeline.
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
