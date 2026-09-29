// Minimal ambient types for the untyped `sql.js` package.
// `sql.js` ships no bundled declarations and no `@types/sql.js` is installed,
// so declare the surface we actually use (see src/localStore.ts).
declare module 'sql.js' {
  type SqlJsConfig = { locateFile?: (file: string) => string }
  const initSqlJs: (config?: SqlJsConfig) => Promise<any>
  export default initSqlJs
}
