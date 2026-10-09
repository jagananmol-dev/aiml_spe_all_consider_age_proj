import { mkdir, readFile, writeFile } from "fs/promises";
import path from "path";

/**
 * VEDA AI — Local file storage (single-machine mode)
 *
 * With STORAGE_BACKEND=local, uploads are written to LOCAL_STORAGE_DIR
 * instead of MinIO, and the documents row gets storage_bucket = "local".
 * The local ingestion worker (services/ingestion/src/workers/local_worker.py)
 * picks them up from the database — no Kafka needed.
 */

export const LOCAL_BUCKET = "local";

export function isLocalStorage(): boolean {
  return process.env.STORAGE_BACKEND === "local";
}

export function getLocalStorageDir(): string {
  // apps/web is the working directory under `next dev`; default to <repo>/.data/uploads
  return path.resolve(
    process.env.LOCAL_STORAGE_DIR || path.join(process.cwd(), "../../.data/uploads")
  );
}

/**
 * Write a file under the storage directory. `relativePath` must be built
 * from server-generated, sanitized parts; it is still checked so it can
 * never escape the storage directory.
 */
export async function saveLocalFile(relativePath: string, data: Buffer): Promise<void> {
  const root = getLocalStorageDir();
  const target = path.resolve(root, relativePath);
  if (!target.startsWith(root + path.sep)) {
    throw new Error("Refusing to write outside the local storage directory");
  }
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, data, { flag: "wx" });
}

/**
 * Read a stored file. The path comes from the database, and is still checked
 * so it can never point outside the storage directory.
 */
export async function readLocalFile(relativePath: string): Promise<Buffer> {
  const root = getLocalStorageDir();
  const target = path.resolve(root, relativePath);
  if (!target.startsWith(root + path.sep)) {
    throw new Error("Refusing to read outside the local storage directory");
  }
  return readFile(target);
}
