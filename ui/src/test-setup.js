import '@testing-library/jest-dom'

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = () => {}

// vitest's jsdom localStorage sometimes lacks clear(); provide a full implementation
const _localStorageStore = {}
const localStorageMock = {
  getItem:    (k) => Object.prototype.hasOwnProperty.call(_localStorageStore, k) ? _localStorageStore[k] : null,
  setItem:    (k, v) => { _localStorageStore[k] = String(v) },
  removeItem: (k) => { delete _localStorageStore[k] },
  clear:      () => { Object.keys(_localStorageStore).forEach(k => delete _localStorageStore[k]) },
  get length() { return Object.keys(_localStorageStore).length },
  key:        (i) => Object.keys(_localStorageStore)[i] ?? null,
}
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true })
