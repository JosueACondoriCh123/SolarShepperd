const DB_NAME = "solarshepherd-private-v1";
const STORE = "sample-drafts";

export interface OfflineSampleDraft {
  key: string;
  userId: string;
  pilotSlug?: string;
  createdAt: string;
  payload: Record<string, unknown>;
  photos?: File[];
  // Backward compatibility for drafts created before multi-photo capture.
  photo?: File;
  lastError?: string;
  retryCount?: number;
  retriedAt?: string;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transaction<T>(
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const request = action(tx.objectStore(STORE));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

export async function saveSampleDraft(draft: OfflineSampleDraft) {
  await transaction("readwrite", (store) => store.put(draft));
}

export async function listSampleDrafts(userId: string, pilotSlug?: string): Promise<OfflineSampleDraft[]> {
  const values = await transaction<OfflineSampleDraft[]>("readonly", (store) => store.getAll());
  return values.filter((item) => item.userId === userId
    && (!pilotSlug || (item.pilotSlug || "jkuat") === pilotSlug));
}

export async function deleteSampleDraft(key: string) {
  await transaction("readwrite", (store) => store.delete(key));
}

export async function countPrivateDrafts(userId: string): Promise<number> {
  return (await listSampleDrafts(userId)).length;
}

export async function clearPrivateDrafts(userId: string) {
  for (const draft of await listSampleDrafts(userId)) {
    await deleteSampleDraft(draft.key);
  }
}
