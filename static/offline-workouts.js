// Workouts kept on this device while offline, until they upload. Shared by the
// service worker (which keeps them) and the pages (which upload them).
// Each item: { id, user, text, savedAt, status: 'pending' | 'failed', error }.
(function (scope) {
  const DB_NAME = 'liftbook-offline';
  const OLD_DB_NAME = 'workout-tracker-offline'; // before the app was called Liftbook
  const STORE = 'workouts';
  let moved = null;

  function openDb(name = DB_NAME) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  // Workouts still waiting under the old name move into the new store once, then
  // the old store is deleted. Any failure leaves them where they are for next time.
  function moveOld() {
    if (moved) return moved;
    moved = (indexedDB.databases ? indexedDB.databases() : Promise.resolve(null))
      .then((list) => {
        if (list && !list.some((d) => d.name === OLD_DB_NAME)) return;
        return openDb(OLD_DB_NAME).then((old) => new Promise((resolve, reject) => {
          const request = old.transaction(STORE, 'readonly').objectStore(STORE).getAll();
          request.onsuccess = () => { old.close(); resolve(request.result || []); };
          request.onerror = () => { old.close(); reject(request.error); };
        })).then((items) => openDb().then((db) => new Promise((resolve, reject) => {
          const tx = db.transaction(STORE, 'readwrite');
          items.forEach((item) => tx.objectStore(STORE).put(item));
          tx.oncomplete = () => { db.close(); resolve(); };
          tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
        }))).then(() => { indexedDB.deleteDatabase(OLD_DB_NAME); });
      })
      .catch(() => { moved = null; });
    return moved;
  }

  function run(mode, work) {
    return moveOld().then(() => openDb()).then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = work(tx.objectStore(STORE));
      tx.oncomplete = () => {
        db.close();
        resolve(request ? request.result : undefined);
      };
      tx.onerror = tx.onabort = () => {
        db.close();
        reject(tx.error);
      };
    }));
  }

  scope.offlineWorkouts = {
    all: () => run('readonly', (store) => store.getAll())
      .then((items) => (items || []).sort((a, b) => a.savedAt - b.savedAt)),
    get: (id) => run('readonly', (store) => store.get(id)),
    put: (item) => run('readwrite', (store) => { store.put(item); }),
    remove: (id) => run('readwrite', (store) => { store.delete(id); }),
  };
})(self);
