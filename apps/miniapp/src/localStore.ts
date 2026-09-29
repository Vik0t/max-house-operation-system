import type { House, HouseState, Issue, Initiative, SignalResult, ViewerRole, WorkOrder } from './types'
import { koltsovoHouses } from './data/koltsovo'
import wasmUrl from 'sql.js/dist/sql-wasm-browser.wasm?url'

const DB_KEY = 'dompuls-sql-db'
let db: { run: (sql: string, params?: unknown[]) => void; exec: (sql: string, params?: unknown[]) => { columns: string[]; values: unknown[][] }[]; export: () => Uint8Array } | null = null
let useWasm = false

// Wipe persisted demo data so the next load re-seeds the original scenario.
export function resetLocalStore() {
  try {
    localStorage.removeItem(DB_KEY)
    localStorage.removeItem(DB_KEY + '-mem')
  } catch { /* ignore */ }
}

function now() { return new Date().toISOString() }
function daysAgo(n: number) { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString() }

// ─── In-memory fallback (no WASM) ─────────────────────────────
type Row = Record<string, unknown>
const mem: Record<string, Row[]> = {
  houses: [], zones: [], assets: [], issues: [], actions: [], signals: [],
  work_orders: [], submissions: [], comments: [], initiatives: [], initiative_votes: [],
}

function memExec(sql: string, params: unknown[] = []): { columns: string[]; values: unknown[][] }[] {
  const trimmed = sql.trim()
  const insertMatch = trimmed.match(/^INSERT\s+INTO\s+(\w+)\s*(?:\(([^)]+)\))?\s*VALUES\s*\((.+)\)$/i)
  if (insertMatch) {
    const [, table, colsStr, valsStr] = insertMatch
    const cols = colsStr ? colsStr.split(',').map((c) => c.trim()) : []
    const placeholders = valsStr.split(',').length
    const values: unknown[] = []
    let pi = 0
    for (let i = 0; i < placeholders; i++) {
      const v = valsStr.split(',')[i].trim()
      if (v === '?' || v === 'NULL' || v === 'null') { values.push(params[pi++] ?? null) }
      else if (v.startsWith("'") && v.endsWith("'")) { values.push(v.slice(1, -1)) }
      else { values.push(params[pi++] ?? v) }
    }
    const row: Row = {}
    if (cols.length) { cols.forEach((c, i) => { row[c] = values[i] }) }
    else { values.forEach((v, i) => { row[`col${i}`] = v }) }
    if (!mem[table]) mem[table] = []
    mem[table].push(row)
    return []
  }

  const insertOrReplace = trimmed.match(/^INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s+VALUES\s*\((.+)\)$/i)
  if (insertOrReplace) {
    const [, table, valsStr] = insertOrReplace
    const values: unknown[] = []
    let pi = 0
    for (const v of valsStr.split(',')) {
      const t = v.trim()
      if (t === '?') values.push(params[pi++])
      else if (t.startsWith("'") && t.endsWith("'")) values.push(t.slice(1, -1))
      else values.push(t)
    }
    const pk = table === 'initiative_votes' ? ['initiative_id', 'voter_id'] : ['id']
    if (!mem[table]) mem[table] = []
    const idx = mem[table].findIndex((r) => pk.every((k) => String(r[k]) === String(values[mem[table]![0] ? Object.keys(mem[table]![0]).indexOf(pk[0]) : 0])))
    const row: Row = {}
    const cols = Object.keys(mem[table]![0] || {})
    cols.forEach((c, i) => { row[c] = values[i] })
    if (idx >= 0) mem[table]![idx] = row; else mem[table]!.push(row)
    return []
  }

  const updateMatch = trimmed.match(/^UPDATE\s+(\w+)\s+SET\s+(.+?)\s+WHERE\s+(.+)$/i)
  if (updateMatch) {
    const [, table, setClause, whereClause] = updateMatch
    const setParts = setClause.split(',').map((s) => s.trim())
    const whereParts = whereClause.split('AND').map((s) => s.trim())
    // SQL binds parameters in text order: SET assignments first, then WHERE.
    let pi = 0
    const updates: Array<{ col: string; val?: unknown; inc?: number }> = []
    for (const sp of setParts) {
      const eqIdx = sp.indexOf('=')
      if (eqIdx < 0) continue
      const col = sp.slice(0, eqIdx).trim()
      const valPart = sp.slice(eqIdx + 1).trim()
      if (valPart === '?') updates.push({ col, val: params[pi++] })
      else if (valPart.includes('+')) {
        const inc = valPart.split('+').map((s) => s.trim()).pop()
        updates.push({ col, inc: Number(inc) || 1 })
      }
      else if (valPart.startsWith("'")) updates.push({ col, val: valPart.slice(1, -1) })
      else updates.push({ col, val: valPart })
    }
    const whereVals: unknown[] = []
    for (const wp of whereParts) {
      const [, , , wVal] = wp.match(/(\w+)\s*(=|LIKE|>|<)\s*(\?|'[^']*'|\d+)/i) || []
      if (wVal === '?') whereVals.push(params[pi++])
      else if (wVal?.startsWith("'")) whereVals.push(wVal.slice(1, -1))
      else whereVals.push(wVal)
    }
    for (const row of (mem[table] || [])) {
      const match = whereParts.every((wp, wi) => {
        const [, wCol] = wp.match(/(\w+)/) || []
        return String(row[wCol]) === String(whereVals[wi])
      })
      if (match) {
        updates.forEach((u) => {
          row[u.col] = u.inc !== undefined ? (Number(row[u.col]) || 0) + u.inc : u.val
        })
      }
    }
    return []
  }

  if (trimmed.startsWith('CREATE TABLE')) return []
  if (trimmed.startsWith('SELECT')) {
    const selectMatch = trimmed.match(/^SELECT\s+(.+?)\s+FROM\s+(\w+)/i)
    if (!selectMatch) return []
    const [, colsPart, table] = selectMatch
    const joinMatch = trimmed.match(/LEFT\s+JOIN\s+(\w+)\s+\w+\s+ON\s+(.+)/i)
    const whereMatch = trimmed.match(/WHERE\s+(.+?)(?:\s+GROUP|\s+ORDER|\s+LIMIT|$)/i)
    const limitMatch = trimmed.match(/LIMIT\s+(\d+)/i)
    const groupMatch = trimmed.match(/GROUP\s+BY\s+(.+)/i)
    const orderMatch = trimmed.match(/ORDER\s+BY\s+(.+?)(?:\s+LIMIT|$)/i)

    let rows = [...(mem[table] || [])]

    if (joinMatch) {
      const [, joinTable, joinOn] = joinMatch
      const [, leftCol] = joinOn.match(/(\w+\.\w+)/) || []
      const [, rightCol] = joinOn.match(/=\s*(\w+\.\w+)/) || []
      const lCol = leftCol?.split('.')[1] || ''
      const rCol = rightCol?.split('.')[1] || ''
      rows = rows.map((r) => {
        const joined = (mem[joinTable] || []).find((j) => String(j[rCol]) === String(r[lCol]))
        return { ...r, issue_title: joined?.title || null, issue_state: joined?.state || null }
      })
    }

    if (whereMatch) {
      const conditions = whereMatch[1].split(/AND/i).map((s) => s.trim())
      // Bind each "?" once, in order, then apply the parsed conditions to every row.
      // (Binding inside the row filter increments the param index per row, so only the
      //  first row would ever match.)
      let pi2 = 0
      const parsed = conditions.map((cond) => {
        const [, wCol, wOp, wVal] = cond.match(/(\w+(?:\.\w+)?)\s*(IS\s+NOT\s+NULL|IS\s+NULL|=|LIKE|!=|>=|<=|>|<)\s*(\?|'[^']*'|\w+)?/i) || []
        if (!wCol || !wOp) return null
        const col = wCol.includes('.') ? wCol.split('.')[1] : wCol
        let val: string
        if (wVal === '?') val = String(params[pi2++])
        else if (wVal?.startsWith("'")) val = wVal.slice(1, -1)
        else val = String(wVal || '')
        return { col, op: wOp.toUpperCase(), val }
      })
      rows = rows.filter((r) => parsed.every((p) => {
        if (!p) return true
        if (p.op === 'IS NOT NULL') return r[p.col] != null
        if (p.op === 'IS NULL') return r[p.col] == null
        if (p.op === '=') return String(r[p.col]) === p.val
        if (p.op === 'LIKE') return String(r[p.col]).toLowerCase().includes(p.val.toLowerCase())
        if (p.op === '!=') return String(r[p.col]) !== p.val
        if (p.op === '>') return Number(r[p.col]) > Number(p.val)
        if (p.op === '<') return Number(r[p.col]) < Number(p.val)
        if (p.op === '>=') return Number(r[p.col]) >= Number(p.val)
        if (p.op === '<=') return Number(r[p.col]) <= Number(p.val)
        return true
      }))
    }

    if (groupMatch) {
      const groupCol = groupMatch[1].trim().split(',')[0].trim()
      const groups = new Map<string, Row[]>()
      for (const r of rows) {
        const key = String(r[groupCol])
        if (!groups.has(key)) groups.set(key, [])
        groups.get(key)!.push(r)
      }
      rows = []
      for (const [, gRows] of groups) {
        const row = { ...gRows[0] }
        if (trimmed.includes('COUNT(*)')) row['cnt'] = gRows.length
        rows.push(row)
      }
    }

    if (orderMatch) {
      const orderCol = orderMatch[1].trim().split(/\s+/)[0].split('.').pop()!
      const desc = orderMatch[1].toUpperCase().includes('DESC')
      rows.sort((a, b) => {
        const av = String(a[orderCol] || ''), bv = String(b[orderCol] || '')
        return desc ? bv.localeCompare(av) : av.localeCompare(bv)
      })
    }

    if (limitMatch) rows = rows.slice(0, Number(limitMatch[1]))

    // Expand `alias.*` / `*` into the base table's columns. Without this a
    // `SELECT s.*, ...` exposes a literal "*" column and every value is null.
    // Union across all rows so a column added to only some rows (e.g. a
    // migration field like decline_reason) is still returned.
    const baseCols = [...new Set((mem[table] || []).flatMap((r) => Object.keys(r)))]
    const cleanCols = colsPart.trim()
    let columns: string[]
    if (cleanCols === '*' || /^[A-Za-z_]\w*\.\*$/.test(cleanCols)) {
      columns = baseCols
    } else {
      columns = []
      for (const raw of cleanCols.split(',')) {
        const token = raw.trim()
        if (/^[A-Za-z_]\w*\.\*$/.test(token)) { columns.push(...baseCols); continue }
        const alias = token.match(/\s+AS\s+(\w+)$/i)?.[1]
        columns.push(alias || token.split('.').pop()!.replace(/\s+/g, ''))
      }
    }
    return [{ columns, values: rows.map((r) => columns.map((c) => r[c] ?? null)) }]
  }

  return []
}

function memPersist() {
  try { localStorage.setItem(DB_KEY + '-mem', JSON.stringify(mem)) } catch { /* quota exceeded */ }
}

function memLoad(): boolean {
  try {
    const saved = localStorage.getItem(DB_KEY + '-mem')
    if (saved) { Object.assign(mem, JSON.parse(saved)); return true }
  } catch { /* corrupted */ }
  return false
}

// ─── Seed data (shared by both WASM and memory modes) ──────────
function seedData() {
  const h = { id: 'demo-house-a', address: 'ул. Пушкина, д. 10', region: 'Москва', management_org: 'УК Пример', configuration_id: 'cfg-1', lat: 55.751244, lng: 37.618423, condition: 'демонстрационный дом' }
  mem.houses = [h, ...koltsovoHouses]
  mem.zones = [
    { id: 'zone-entrance-1', house_id: h.id, name: 'Подъезд 1' },
    { id: 'zone-entrance-2', house_id: h.id, name: 'Подъезд 2' },
    { id: 'zone-parking', house_id: h.id, name: 'Парковка' },
    { id: 'zone-elevator-2', house_id: h.id, name: 'Лифт' },
  ]
  mem.assets = [
    { id: 'asset-light-entrance-1', house_id: h.id, zone_id: 'zone-entrance-1', type: 'lighting', name: 'Освещение подъезда 1', operational_state: 'ACTIVE_ISSUE' },
    { id: 'asset-door-entrance-1', house_id: h.id, zone_id: 'zone-entrance-1', type: 'door', name: 'Дверь подъезда 1', operational_state: 'ACTIVE_ISSUE' },
    { id: 'asset-light-entrance-2', house_id: h.id, zone_id: 'zone-entrance-2', type: 'lighting', name: 'Освещение подъезда 2', operational_state: 'HEALTHY' },
    { id: 'asset-elevator-2', house_id: h.id, zone_id: 'zone-elevator-2', type: 'elevator', name: 'Лифт (2 подъезд)', operational_state: 'ACTIVE_ISSUE' },
    { id: 'asset-light-parking', house_id: h.id, zone_id: 'zone-parking', type: 'lighting', name: 'Фонарь парковки', operational_state: 'HEALTHY' },
    { id: 'asset-parking-gate', house_id: h.id, zone_id: 'zone-parking', type: 'door', name: 'Шлагбаум', operational_state: 'HEALTHY' },
  ]
  mem.issues = [
    { id: 'issue-1', house_id: h.id, zone_id: 'zone-entrance-1', asset_id: 'asset-light-entrance-1', category: 'lighting', title: 'Освещение: лампочка не горит на 3 этаже', description: 'В подъезде не горит лампочка на 3 этаже. Темно, невозможно нормально подняться.', severity: 'MEDIUM', state: 'NEEDS_CONFIRMATION', confirmations_count: 2, recurrence_count: 3, asset_name: 'Освещение подъезда 1', zone_name: 'Подъезд 1', related_issue_count: 1, signals_count: 2, provenance: 'USER', first_seen_at: daysAgo(1) },
    { id: 'issue-2', house_id: h.id, zone_id: 'zone-entrance-1', asset_id: 'asset-door-entrance-1', category: 'door', title: 'Дверь: не закрывается входная дверь', description: 'Входная дверь подъезда не закрывается, сквозняк.', severity: 'HIGH', state: 'CONFIRMED', confirmations_count: 4, recurrence_count: 1, asset_name: 'Дверь подъезда 1', zone_name: 'Подъезд 1', related_issue_count: 0, signals_count: 3, provenance: 'USER', first_seen_at: daysAgo(3) },
    { id: 'issue-3', house_id: h.id, zone_id: 'zone-parking', asset_id: 'asset-light-parking', category: 'lighting', title: 'Освещение: нужен второй фонарь на парковке', description: 'Тёмный угол парковки, неудобно и небезопасно.', severity: 'LOW', state: 'ACTION_READY', confirmations_count: 5, recurrence_count: 1, asset_name: 'Фонарь парковки', zone_name: 'Парковка', related_issue_count: 0, signals_count: 5, provenance: 'USER', first_seen_at: daysAgo(5) },
    { id: 'issue-4', house_id: h.id, zone_id: 'zone-elevator-2', asset_id: 'asset-elevator-2', category: 'elevator', title: 'Лифт: остановился на 2 этаже', description: 'Лифт не открывает двери, пассажиры застряли.', severity: 'CRITICAL', state: 'WORK_IN_PROGRESS', confirmations_count: 1, recurrence_count: 1, asset_name: 'Лифт (2 подъезд)', zone_name: 'Лифт', related_issue_count: 0, signals_count: 1, provenance: 'USER', first_seen_at: daysAgo(0) },
    { id: 'issue-5', house_id: h.id, zone_id: 'zone-entrance-2', asset_id: null, category: 'water', title: 'Вода: протечка в подвале', description: 'Затопление в подвале, вода на полу.', severity: 'HIGH', state: 'DONE_PENDING_VERIFICATION', confirmations_count: 3, recurrence_count: 2, asset_name: 'Водоснабжение', zone_name: 'Подъезд 2', related_issue_count: 1, signals_count: 4, provenance: 'USER', first_seen_at: daysAgo(7) },
  ]
  mem.actions = [
    { id: 'action-1', issue_id: 'issue-3', suggested_destination: 'УК', rationale: 'Передать в УК для планирования работ', confidence: 0.85, provenance: 'CALCULATED' },
    { id: 'action-2', issue_id: 'issue-4', suggested_destination: 'emergency', rationale: 'Вызвать аварийную службу лифта', confidence: 0.95, provenance: 'CALCULATED' },
  ]
  mem.signals = [
    { id: 'sig-1', issue_id: 'issue-1', chat_id: null, author_id: 'resident-1', source_type: 'max_message', text: 'в подъезде не горит лампочка на 3 этаже', attachments: '[]', provenance: 'USER', created_at: daysAgo(1), status: 'CLUSTERED' },
    { id: 'sig-2', issue_id: 'issue-1', chat_id: null, author_id: 'resident-2', source_type: 'max_message', text: 'тоже темно в подъезде на 3', attachments: '[]', provenance: 'USER', created_at: daysAgo(1), status: 'CLUSTERED' },
    { id: 'sig-3', issue_id: 'issue-2', chat_id: null, author_id: 'resident-3', source_type: 'max_message', text: 'дверь опять не закрывается', attachments: '[]', provenance: 'USER', created_at: daysAgo(3), status: 'CLUSTERED' },
    { id: 'sig-4', issue_id: 'issue-3', chat_id: null, author_id: 'resident-4', source_type: 'max_message', text: 'на парковке нужен второй фонарь', attachments: '[]', provenance: 'USER', created_at: daysAgo(5), status: 'CLUSTERED' },
    { id: 'sig-5', issue_id: 'issue-3', chat_id: null, author_id: 'resident-5', source_type: 'max_message', text: 'тёмный угол, страшно ходить', attachments: '[]', provenance: 'USER', created_at: daysAgo(4), status: 'CLUSTERED' },
    { id: 'sig-6', issue_id: 'issue-4', chat_id: null, author_id: 'resident-6', source_type: 'max_message', text: 'лифт встал на 2 этаже', attachments: '[]', provenance: 'USER', created_at: daysAgo(0), status: 'CLUSTERED' },
    { id: 'sig-7', issue_id: 'issue-5', chat_id: null, author_id: 'resident-7', source_type: 'max_message', text: 'протечка в подвале', attachments: '[]', provenance: 'USER', created_at: daysAgo(7), status: 'CLUSTERED' },
    { id: 'sig-8', issue_id: 'issue-5', chat_id: null, author_id: 'resident-8', source_type: 'web', text: 'вода на полу в подвале', attachments: '[]', provenance: 'USER', created_at: daysAgo(6), status: 'CLUSTERED' },
  ]
  mem.work_orders = [
    { id: 'wo-1', issue_id: 'issue-4', status: 'IN_PROGRESS', assignee_id: 'executor-1', title: 'Вызвать аварийную службу лифта', evidence: '[]' },
  ]
  mem.submissions = [
    { id: 'sub-1', issue_id: 'issue-3', is_simulated: 1, destination_id: 'uk-demo' },
  ]
  mem.comments = [
    { id: 'com-1', issue_id: 'issue-4', author_id: 'uk-1', author_role: 'uk', text: 'Обращение принято, передали аварийной службе лифта.', created_at: daysAgo(0) },
    { id: 'com-2', issue_id: 'issue-4', author_id: 'executor-1', author_role: 'executor', text: 'Выехал на объект, буду на месте через 20 минут.', created_at: daysAgo(0) },
    { id: 'com-3', issue_id: 'issue-3', author_id: 'representative-1', author_role: 'representative', text: 'Собрали 5 подтверждений от жильцов, готово к передаче в УК.', created_at: daysAgo(4) },
  ]
  mem.initiatives = [
    { id: 'init-1', title: 'Установить детскую площадку', summary: 'Предложение установить новую детскую площадку во дворе вместо старых качелей.', options: '["За установку","Против"]', votes: '{"За установку":12,"Против":6}', state: 'INFORMAL_POLL', requires_formal_process: 0, formal_handoff_type: null, provenance: 'USER' },
    { id: 'init-2', title: 'Цифровой домофон', summary: 'Заменить старые домофоны на цифровые с видеокамерами.', options: '["За установку","Против"]', votes: '{"За установку":8,"Против":2}', state: 'INFORMAL_POLL', requires_formal_process: 0, formal_handoff_type: null, provenance: 'USER' },
  ]
  mem.initiative_votes = [
    { initiative_id: 'init-1', voter_id: 'resident-1', option: 'За установку' },
    { initiative_id: 'init-1', voter_id: 'resident-2', option: 'За установку' },
    { initiative_id: 'init-2', voter_id: 'resident-1', option: 'За установку' },
  ]
}

// ─── WASM init ─────────────────────────────────────────────────
async function tryInitWasm(): Promise<boolean> {
  try {
    const initSqlJs = (await import('sql.js')).default
    // Serve the wasm from our own bundle: sql.js.org only hosts sql-wasm.wasm,
    // while the browser entrypoint requests sql-wasm-browser.wasm (404 on the CDN).
    const SQL = await initSqlJs({ locateFile: () => wasmUrl })
    const saved = localStorage.getItem(DB_KEY)
    if (saved) {
      const buf = Uint8Array.from(atob(saved), (c) => c.charCodeAt(0))
      db = new SQL.Database(buf)
    } else {
      db = new SQL.Database()
      // Seed via WASM
      const run = (sql: string, params: unknown[] = []) => (db as any).run(sql, params)
      run(`CREATE TABLE IF NOT EXISTS houses (id TEXT PRIMARY KEY, address TEXT, region TEXT, management_org TEXT, configuration_id TEXT, lat REAL, lng REAL, condition TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS zones (id TEXT PRIMARY KEY, house_id TEXT, name TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, house_id TEXT, zone_id TEXT, type TEXT, name TEXT, operational_state TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, house_id TEXT, zone_id TEXT, asset_id TEXT, category TEXT, title TEXT, description TEXT, severity TEXT, state TEXT, confirmations_count INTEGER DEFAULT 0, recurrence_count INTEGER DEFAULT 0, asset_name TEXT, zone_name TEXT, related_issue_count INTEGER DEFAULT 0, signals_count INTEGER DEFAULT 0, provenance TEXT, first_seen_at TEXT, decline_reason TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, issue_id TEXT, suggested_destination TEXT, rationale TEXT, confidence REAL, provenance TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, issue_id TEXT, chat_id TEXT, author_id TEXT, source_type TEXT, text TEXT, attachments TEXT, provenance TEXT, created_at TEXT, status TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS work_orders (id TEXT PRIMARY KEY, issue_id TEXT, status TEXT, assignee_id TEXT, title TEXT, evidence TEXT DEFAULT '[]')`)
      run(`CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, issue_id TEXT, is_simulated INTEGER, destination_id TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, issue_id TEXT, author_id TEXT, author_role TEXT, text TEXT, created_at TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS photos (id TEXT PRIMARY KEY, issue_id TEXT, comment_id TEXT, data TEXT, created_at TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS initiatives (id TEXT PRIMARY KEY, title TEXT, summary TEXT, options TEXT, votes TEXT, state TEXT, requires_formal_process INTEGER, formal_handoff_type TEXT, provenance TEXT)`)
      run(`CREATE TABLE IF NOT EXISTS initiative_votes (initiative_id TEXT, voter_id TEXT, option TEXT, PRIMARY KEY (initiative_id, voter_id))`)

      // Seed data into WASM db
      const h = { id: 'demo-house-a', address: 'ул. Пушкина, д. 10', region: 'Москва', management_org: 'УК Пример', configuration_id: 'cfg-1' }
      for (const house of mem.houses) run('INSERT INTO houses (id,address,region,management_org,configuration_id,lat,lng,condition) VALUES (?,?,?,?,?,?,?,?)', [house.id, house.address, house.region, house.management_org, house.configuration_id, house.lat ?? null, house.lng ?? null, house.condition ?? null])
      for (const z of [['zone-entrance-1',h.id,'Подъезд 1'],['zone-entrance-2',h.id,'Подъезд 2'],['zone-parking',h.id,'Парковка'],['zone-elevator-2',h.id,'Лифт']]) run('INSERT INTO zones VALUES (?,?,?)', z)
      for (const a of mem.assets) run('INSERT INTO assets VALUES (?,?,?,?,?,?)', [a.id,a.house_id,a.zone_id,a.type,a.name,a.operational_state])
      for (const i of mem.issues) run('INSERT INTO issues (id,house_id,zone_id,asset_id,category,title,description,severity,state,confirmations_count,recurrence_count,asset_name,zone_name,related_issue_count,signals_count,provenance,first_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [i.id,i.house_id,i.zone_id,i.asset_id,i.category,i.title,i.description,i.severity,i.state,i.confirmations_count,i.recurrence_count,i.asset_name,i.zone_name,i.related_issue_count,i.signals_count,i.provenance,i.first_seen_at])
      for (const a of mem.actions) run('INSERT INTO actions VALUES (?,?,?,?,?,?)', [a.id,a.issue_id,a.suggested_destination,a.rationale,a.confidence,a.provenance])
      for (const s of mem.signals) run('INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?)', [s.id,s.issue_id,s.chat_id,s.author_id,s.source_type,s.text,s.attachments,s.provenance,s.created_at,s.status])
      for (const w of mem.work_orders) run('INSERT INTO work_orders VALUES (?,?,?,?,?,?)', [w.id,w.issue_id,w.status,w.assignee_id,w.title,w.evidence])
      for (const s of mem.submissions) run('INSERT INTO submissions VALUES (?,?,?,?)', [s.id,s.issue_id,s.is_simulated,s.destination_id])
      for (const c of mem.comments) run('INSERT INTO comments VALUES (?,?,?,?,?,?)', [c.id,c.issue_id,c.author_id,c.author_role,c.text,c.created_at])
      for (const ini of mem.initiatives) run('INSERT INTO initiatives VALUES (?,?,?,?,?,?,?,?,?)', [ini.id,ini.title,ini.summary,ini.options,ini.votes,ini.state,ini.requires_formal_process,ini.formal_handoff_type,ini.provenance])
      for (const v of mem.initiative_votes) run('INSERT INTO initiative_votes VALUES (?,?,?)', [v.initiative_id,v.voter_id,v.option])
      wasmPersist()
    }
    // Idempotent schema migrations for databases saved by older versions.
    const migrate = (sql: string) => { try { (db as any).run(sql) } catch { /* already applied */ } }
    migrate(`CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, issue_id TEXT, author_id TEXT, author_role TEXT, text TEXT, created_at TEXT)`)
    migrate(`CREATE TABLE IF NOT EXISTS photos (id TEXT PRIMARY KEY, issue_id TEXT, comment_id TEXT, data TEXT, created_at TEXT)`)
    migrate(`ALTER TABLE issues ADD COLUMN decline_reason TEXT`)
    migrate(`ALTER TABLE houses ADD COLUMN lat REAL`)
    migrate(`ALTER TABLE houses ADD COLUMN lng REAL`)
    migrate(`ALTER TABLE houses ADD COLUMN condition TEXT`)
    useWasm = true
    return true
  } catch {
    return false
  }
}

function wasmPersist() {
  if (!db) return
  const data = (db as any).export() as Uint8Array
  // Chunk the byte -> char conversion: spreading hundreds of thousands of bytes
  // into String.fromCharCode overflows the argument limit and throws.
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < data.length; i += chunk) {
    binary += String.fromCharCode(...data.subarray(i, i + chunk))
  }
  try { localStorage.setItem(DB_KEY, btoa(binary)) } catch { /* quota exceeded */ }
}

function exec(sql: string, params: unknown[] = []): { columns: string[]; values: unknown[][] }[] {
  if (useWasm && db) return (db as any).exec(sql, params) || []
  return memExec(sql, params)
}

function runSql(sql: string, params: unknown[] = []) {
  if (useWasm && db) { (db as any).run(sql, params); wasmPersist() }
  else { memExec(sql, params); memPersist() }
}

// ─── Shared row mappers ────────────────────────────────────────
function rowToIssue(row: Row): Issue {
  const issue: Issue = {
    id: String(row.id), house_id: String(row.house_id),
    zone_id: row.zone_id as string | null, asset_id: row.asset_id as string | null,
    category: String(row.category), title: String(row.title),
    description: String(row.description || ''), severity: String(row.severity || 'MEDIUM'),
    state: String(row.state), confirmations_count: Number(row.confirmations_count) || 0,
    recurrence_count: Number(row.recurrence_count) || 0,
    asset_name: row.asset_name as string | null, zone_name: row.zone_name as string | null,
    related_issue_count: Number(row.related_issue_count) || 0, related_issue_ids: [],
    signals_count: Number(row.signals_count) || 0,
    provenance: String(row.provenance || 'USER'), first_seen_at: String(row.first_seen_at || now()),
    decline_reason: (row.decline_reason as string | null) ?? null,
  }

  const aRows = exec("SELECT * FROM actions WHERE issue_id=?", [issue.id])
  if (aRows[0]?.values[0]) {
    const a = aRows[0].values[0]; const c = aRows[0].columns
    issue.actions = [{ id: String(a[c.indexOf('id')]), suggested_destination: String(a[c.indexOf('suggested_destination')] || ''), rationale: String(a[c.indexOf('rationale')] || ''), confidence: Number(a[c.indexOf('confidence')] || 0), provenance: String(a[c.indexOf('provenance')] || '') }]
  }
  const sRows = exec("SELECT * FROM submissions WHERE issue_id=?", [issue.id])
  if (sRows[0]?.values.length) {
    issue.submissions = sRows[0].values.map((s) => { const c = sRows![0].columns; return { id: String(s[c.indexOf('id')]), is_simulated: Boolean(s[c.indexOf('is_simulated')]), destination_id: String(s[c.indexOf('destination_id')]) } })
  }
  const sigRows = exec("SELECT * FROM signals WHERE issue_id=? ORDER BY created_at DESC", [issue.id])
  if (sigRows[0]?.values.length) {
    issue.signals = sigRows[0].values.map((s) => { const c = sigRows![0].columns; return { id: String(s[c.indexOf('id')]), chat_id: s[c.indexOf('chat_id')] as string | null, author_id: String(s[c.indexOf('author_id')]), source_type: String(s[c.indexOf('source_type')]), text: String(s[c.indexOf('text')]), attachments: JSON.parse(String(s[c.indexOf('attachments')] || '[]')), provenance: String(s[c.indexOf('provenance')]), created_at: String(s[c.indexOf('created_at')]), status: s[c.indexOf('status')] as 'CLUSTERED' | 'AWAITING_CONTEXT' | undefined, issue: null } })
  }
  const woRows = exec("SELECT * FROM work_orders WHERE issue_id=? ORDER BY rowid DESC", [issue.id])
  if (woRows[0]?.values.length) {
    issue.work_orders = woRows[0].values.map((w) => { const c = woRows![0].columns; return { id: String(w[c.indexOf('id')]), status: String(w[c.indexOf('status')]), assignee_id: String(w[c.indexOf('assignee_id')]), title: String(w[c.indexOf('title')]), evidence: JSON.parse(String(w[c.indexOf('evidence')] || '[]')) } as WorkOrder })
  }
  const comRows = exec("SELECT * FROM comments WHERE issue_id=? ORDER BY created_at ASC", [issue.id])
  const photoRows = exec("SELECT * FROM photos WHERE issue_id=?", [issue.id])
  const issuePhotos: string[] = []
  const commentPhotos = new Map<string, string[]>()
  if (photoRows[0]?.values.length) {
    const pc = photoRows[0].columns
    for (const v of photoRows[0].values) {
      const data = String(v[pc.indexOf('data')] || '')
      if (!data) continue
      const commentId = v[pc.indexOf('comment_id')]
      if (commentId == null || commentId === '') issuePhotos.push(data)
      else {
        const key = String(commentId)
        const list = commentPhotos.get(key) || []
        list.push(data)
        commentPhotos.set(key, list)
      }
    }
  }
  if (issuePhotos.length) issue.photos = issuePhotos
  if (comRows[0]?.values.length) {
    issue.comments = comRows[0].values.map((v) => { const c = comRows![0].columns; const id = String(v[c.indexOf('id')]); return { id, issue_id: String(v[c.indexOf('issue_id')]), author_id: String(v[c.indexOf('author_id')]), author_role: String(v[c.indexOf('author_role')]), text: String(v[c.indexOf('text')]), created_at: String(v[c.indexOf('created_at')]), photos: commentPhotos.get(id) } })
  }
  return issue
}

function rowToInitiative(row: Row): Initiative {
  const votes: Record<string, number> = {}
  try { Object.assign(votes, JSON.parse(String(row.votes || '{}'))) } catch { /* empty */ }
  return { id: String(row.id), title: String(row.title), summary: String(row.summary || ''), options: JSON.parse(String(row.options || '[]')), votes, state: String(row.state), requires_formal_process: Boolean(row.requires_formal_process), formal_handoff_type: row.formal_hand_type as string | null, provenance: String(row.provenance || 'USER') }
}

// ─── Init ──────────────────────────────────────────────────────
let initPromise: Promise<void> | null = null
function init(): Promise<void> {
  if (!initPromise) {
    initPromise = (async () => {
      if (!memLoad()) seedData()
      await tryInitWasm()
    })()
  }
  return initPromise
}

// ─── Public API ────────────────────────────────────────────────
export const localStore = {
  async ensureReady() { await init() },

  async houses(): Promise<House[]> {
    await init()
    const r = exec('SELECT * FROM houses')
    if (!r[0]) return []
    const c = r[0].columns
    return r[0].values.map((v) => ({ id: String(v[c.indexOf('id')]), address: String(v[c.indexOf('address')]), region: String(v[c.indexOf('region')]), management_org: String(v[c.indexOf('management_org')]), configuration_id: String(v[c.indexOf('configuration_id')]), lat: v[c.indexOf('lat')] == null ? null : Number(v[c.indexOf('lat')]), lng: v[c.indexOf('lng')] == null ? null : Number(v[c.indexOf('lng')]), condition: v[c.indexOf('condition')] == null ? null : String(v[c.indexOf('condition')]) }))
  },

  async state(houseId: string, viewerId: string | number | undefined, role: ViewerRole): Promise<HouseState> {
    await init()
    const hr = exec('SELECT * FROM houses WHERE id=?', [houseId])
    const h = hr[0]?.values[0]
    if (!h) throw new Error('House not found')
    const hc = hr[0].columns
    const house: House = { id: String(h[hc.indexOf('id')]), address: String(h[hc.indexOf('address')]), region: String(h[hc.indexOf('region')]), management_org: String(h[hc.indexOf('management_org')]), configuration_id: String(h[hc.indexOf('configuration_id')]), lat: h[hc.indexOf('lat')] == null ? null : Number(h[hc.indexOf('lat')]), lng: h[hc.indexOf('lng')] == null ? null : Number(h[hc.indexOf('lng')]), condition: h[hc.indexOf('condition')] == null ? null : String(h[hc.indexOf('condition')]) }

    const ar = exec('SELECT * FROM assets WHERE house_id=?', [houseId])
    const assets: HouseState['assets'] = (ar[0]?.values || []).map((v) => { const c = ar[0].columns; return { id: String(v[c.indexOf('id')]), house_id: String(v[c.indexOf('house_id')]), zone_id: String(v[c.indexOf('zone_id')]), type: String(v[c.indexOf('type')]), name: String(v[c.indexOf('name')]), operational_state: String(v[c.indexOf('operational_state')]) } })

    const ir = exec('SELECT * FROM issues WHERE house_id=?', [houseId])
    const allIssues = (ir[0]?.values || []).map((v) => { const c = ir[0].columns; const row: Row = {}; c.forEach((col, i) => { row[col] = v[i] }); return rowToIssue(row) })

    const iniR = exec('SELECT * FROM initiatives')
    const initiatives = (iniR[0]?.values || []).map((v) => { const c = iniR[0].columns; const row: Row = {}; c.forEach((col, i) => { row[col] = v[i] }); return rowToInitiative(row) })

    const sigR = exec('SELECT s.*, si.title AS issue_title, si.state AS issue_state FROM signals s LEFT JOIN issues si ON s.issue_id=si.id WHERE s.issue_id IS NOT NULL ORDER BY s.created_at DESC LIMIT 10')
    const recent_signals = (sigR[0]?.values || []).map((v) => { const c = sigR[0].columns; return { id: String(v[c.indexOf('id')]), chat_id: v[c.indexOf('chat_id')] as string | null, author_id: String(v[c.indexOf('author_id')]), source_type: String(v[c.indexOf('source_type')]), text: String(v[c.indexOf('text')]), attachments: JSON.parse(String(v[c.indexOf('attachments')] || '[]')), provenance: String(v[c.indexOf('provenance')]), created_at: String(v[c.indexOf('created_at')]), status: v[c.indexOf('status')] as 'CLUSTERED' | 'AWAITING_CONTEXT' | undefined, issue: v[c.indexOf('issue_title')] ? { id: String(v[c.indexOf('issue_id')]), title: String(v[c.indexOf('issue_title')]), state: String(v[c.indexOf('issue_state')]) } : null } })

    // Archive = approved/closed and declined requests.
    const archiveStates = ['CLOSED', 'VERIFIED', 'DECLINED']
    const closedIssues = allIssues.filter((i) => archiveStates.includes(i.state))
    const openIssues = allIssues.filter((i) => !archiveStates.includes(i.state))

    let my_tasks: HouseState['my_tasks'] = []
    if (role === 'resident') my_tasks = openIssues.map((i) => ({ ...i, next_action: { id: 'open', label: i.state === 'DONE_PENDING_VERIFICATION' ? 'Проверить результат' : 'Открыть' } }))
    else if (role === 'representative') my_tasks = openIssues.filter((i) => ['NEEDS_CONFIRMATION', 'CONFIRMED', 'ACTION_READY', 'REOPENED'].includes(i.state)).map((i) => ({ ...i, next_action: i.state === 'ACTION_READY' ? { id: 'submit', label: 'Передать в УК' } : i.state === 'REOPENED' ? { id: 'submit', label: 'Переотправить в УК' } : { id: 'confirm', label: 'Подтвердить' } }))
    else if (role === 'uk') my_tasks = openIssues.filter((i) => ['SUBMITTED', 'ACCEPTED', 'REOPENED'].includes(i.state)).map((i) => ({ ...i, next_action: i.state === 'SUBMITTED' ? { id: 'accept', label: 'Принять' } : { id: 'create-order', label: 'Назначить исполнителя' } }))
    else if (role === 'executor') my_tasks = openIssues.filter((i) => { const o = i.work_orders?.at(-1); return o ? ['ASSIGNED', 'IN_PROGRESS', 'REWORK_REQUIRED'].includes(o.status) : false }).map((i) => { const o = i.work_orders!.at(-1)!; const label = o.status === 'ASSIGNED' ? 'Начать работу' : o.status === 'REWORK_REQUIRED' ? 'Начать доработку' : o.evidence.length ? 'Завершить работу' : 'Добавить фото'; return { ...i, next_action: { id: 'open', label } } })
    else if (role === 'admin') my_tasks = openIssues.map((i) => ({ ...i, next_action: { id: 'open', label: 'Проверить' } }))

    return {
      house, assets,
      metrics: { active_issues: openIssues.length, work_in_progress: openIssues.filter((i) => i.state === 'WORK_IN_PROGRESS').length, awaiting_confirmation: openIssues.filter((i) => i.state === 'NEEDS_CONFIRMATION').length, submitted_to_management: openIssues.filter((i) => i.state === 'SUBMITTED').length, awaiting_verification: openIssues.filter((i) => i.state === 'DONE_PENDING_VERIFICATION').length, recurring_issues: openIssues.filter((i) => i.recurrence_count >= 2).length, initiatives: initiatives.length },
      issues: openIssues, my_tasks, history_issues: closedIssues, initiatives, recent_signals,
      integration: { max: 'SIMULATED', external_submission: 'SIMULATED' },
    }
  },

  async issue(issueId: string): Promise<Issue> {
    await init()
    const r = exec('SELECT * FROM issues WHERE id=?', [issueId])
    if (!r[0]?.values[0]) throw new Error('Issue not found')
    const c = r[0].columns; const row: Row = {}
    c.forEach((col, i) => { row[col] = r[0].values[0][i] })
    return rowToIssue(row)
  },

  async signal(houseId: string, text: string, _manualZoneId?: string, forceAiFailure = false, photos: string[] = []): Promise<SignalResult> {
    await init()
    if (forceAiFailure) return { fallback: { type: 'CLARIFICATION_NEEDED', message: 'Не удалось определить объект. Уточните:', choices: [{ id: 'elevator', name: 'Лифт' }, { id: 'lighting', name: 'Освещение' }, { id: 'water', name: 'Водоснабжение' }, { id: 'other', name: 'Другое' }] } }
    const id = `issue-${Date.now()}`, sigId = `sig-${Date.now()}`
    runSql('INSERT INTO issues (id,house_id,category,title,description,severity,state,confirmations_count,recurrence_count,provenance,first_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)', [id, houseId, 'other', text.slice(0, 60), text, 'MEDIUM', 'NEEDS_CONFIRMATION', 1, 0, 'USER', now()])
    runSql('INSERT INTO signals (id,issue_id,author_id,source_type,text,attachments,provenance,created_at,status) VALUES (?,?,?,?,?,?,?,?,?)', [sigId, id, 'web-user', 'web', text, '[]', 'USER', now(), 'CLUSTERED'])
    photos.forEach((data, index) => runSql('INSERT INTO photos (id,issue_id,comment_id,data,created_at) VALUES (?,?,?,?,?)', [`ph-${Date.now()}-${index}`, id, null, data, now()]))
    return { signal: { id: sigId }, issue: await localStore.issue(id) }
  },

  async resolveDuplicate(_signalId: string, candidateIssueId: string, _decision: 'LINK' | 'CREATE_NEW'): Promise<Issue> {
    await init(); return localStore.issue(candidateIssueId)
  },

  // Staff (and residents) can leave notes/clarifications on an issue.
  async addComment(issueId: string, text: string, authorRole: string, authorId: string, photos: string[] = []): Promise<Issue> {
    await init()
    const commentId = `com-${Date.now()}`
    runSql('INSERT INTO comments (id,issue_id,author_id,author_role,text,created_at) VALUES (?,?,?,?,?,?)', [commentId, issueId, authorId, authorRole, text, now()])
    photos.forEach((data, index) => runSql('INSERT INTO photos (id,issue_id,comment_id,data,created_at) VALUES (?,?,?,?,?)', [`ph-${commentId}-${index}`, issueId, commentId, data, now()]))
    return localStore.issue(issueId)
  },

  // Admins decline a request with a reason; it moves to the archive.
  async decline(issueId: string, reason: string, _actorId: string): Promise<Issue> {
    await init()
    runSql("UPDATE issues SET state='DECLINED', decline_reason=? WHERE id=?", [reason, issueId])
    return localStore.issue(issueId)
  },

  async addHouse(house: House): Promise<House> {
    await init()
    runSql('INSERT INTO houses (id,address,region,management_org,configuration_id,lat,lng,condition) VALUES (?,?,?,?,?,?,?,?)', [house.id, house.address, house.region, house.management_org, house.configuration_id, house.lat ?? null, house.lng ?? null, house.condition ?? null])
    return house
  },

  // A representative vouches for the problem: it becomes ready to hand off.
  async confirm(issueId: string): Promise<Issue> {
    await init()
    runSql("UPDATE issues SET state='ACTION_READY', confirmations_count=confirmations_count+1 WHERE id=?", [issueId])
    return localStore.issue(issueId)
  },
  async prepare(issueId: string): Promise<Issue> {
    await init()
    runSql("UPDATE issues SET state='ACTION_READY' WHERE id=? AND state='CONFIRMED'", [issueId])
    return localStore.issue(issueId)
  },
  // A resident adds their voice; enough voices also make it ready to hand off.
  async residentConfirm(issueId: string, _actorId: string): Promise<{ issue: Issue }> {
    await init()
    const current = await localStore.issue(issueId)
    const count = current.confirmations_count + 1
    const promote = count >= 3 && ['NEEDS_CONFIRMATION', 'DETECTED', 'CONFIRMED'].includes(current.state)
    runSql('UPDATE issues SET confirmations_count=?, state=? WHERE id=?', [count, promote ? 'ACTION_READY' : current.state, issueId])
    return { issue: await localStore.issue(issueId) }
  },
  async submit(issueId: string): Promise<Issue> {
    await init(); runSql("UPDATE issues SET state='SUBMITTED' WHERE id=?", [issueId]); return localStore.issue(issueId)
  },
  async accept(issueId: string): Promise<Issue> {
    await init(); runSql("UPDATE issues SET state='ACCEPTED' WHERE id=?", [issueId]); return localStore.issue(issueId)
  },

  async createWorkOrder(issueId: string): Promise<WorkOrder> {
    await init()
    const woId = `wo-${Date.now()}`
    runSql('INSERT INTO work_orders (id,issue_id,status,assignee_id,title,evidence) VALUES (?,?,?,?,?,?)', [woId, issueId, 'ASSIGNED', 'executor-1', 'Назначенная работа', '[]'])
    runSql("UPDATE issues SET state='WORK_IN_PROGRESS' WHERE id=?", [issueId])
    return { id: woId, status: 'ASSIGNED', assignee_id: 'executor-1', title: 'Назначенная работа', evidence: [] }
  },
  async updateWorkOrder(orderId: string, status: string): Promise<WorkOrder> {
    await init()
    runSql('UPDATE work_orders SET status=? WHERE id=?', [status, orderId])
    // Keep the issue in sync so the next role sees the right next step.
    const issueState = status === 'DONE' ? 'DONE_PENDING_VERIFICATION' : (status === 'IN_PROGRESS' || status === 'REWORK_REQUIRED') ? 'WORK_IN_PROGRESS' : null
    if (issueState) {
      const or = exec('SELECT issue_id FROM work_orders WHERE id=?', [orderId])
      const issueId = or[0]?.values[0]?.[0]
      if (issueId) runSql('UPDATE issues SET state=? WHERE id=?', [issueState, String(issueId)])
    }
    const r = exec('SELECT * FROM work_orders WHERE id=?', [orderId])
    if (!r[0]?.values[0]) throw new Error('Work order not found')
    const c = r[0].columns, v = r[0].values[0]
    return { id: String(v[c.indexOf('id')]), status: String(v[c.indexOf('status')]), assignee_id: String(v[c.indexOf('assignee_id')]), title: String(v[c.indexOf('title')]), evidence: JSON.parse(String(v[c.indexOf('evidence')] || '[]')) }
  },
  async evidence(orderId: string): Promise<WorkOrder> {
    await init()
    const r = exec('SELECT evidence FROM work_orders WHERE id=?', [orderId])
    if (!r[0]?.values[0]) throw new Error('Work order not found')
    const ev = JSON.parse(String(r[0].values[0][0] || '[]'))
    ev.push({ id: `ev-${Date.now()}`, type: 'after_photo', uri: '/demo/elevator-after.svg', comment: 'Контрольный запуск выполнен, кабина работает штатно.', created_at: now() })
    runSql('UPDATE work_orders SET evidence=? WHERE id=?', [JSON.stringify(ev), orderId])
    return localStore.updateWorkOrder(orderId, 'IN_PROGRESS')
  },

  async verify(issueId: string, result: 'confirmed' | 'rejected', _verifierId: string): Promise<Issue> {
    await init(); runSql('UPDATE issues SET state=? WHERE id=?', [result === 'confirmed' ? 'VERIFIED' : 'REOPENED', issueId]); return localStore.issue(issueId)
  },

  async vote(initiativeId: string, voterId: string, option: string): Promise<Initiative> {
    await init()
    runSql('INSERT OR REPLACE INTO initiative_votes VALUES (?,?,?)', [initiativeId, voterId, option])
    const vr = exec('SELECT option, COUNT(*) as cnt FROM initiative_votes WHERE initiative_id=? GROUP BY option', [initiativeId])
    const votes: Record<string, number> = {}
    if (vr[0]) vr[0].values.forEach((v) => { votes[String(v[0])] = Number(v[1]) })
    runSql('UPDATE initiatives SET votes=? WHERE id=?', [JSON.stringify(votes), initiativeId])
    const r = exec('SELECT * FROM initiatives WHERE id=?', [initiativeId])
    if (!r[0]?.values[0]) throw new Error('Initiative not found')
    const c = r[0].columns; const row: Row = {}; c.forEach((col, i) => { row[col] = r[0].values[0][i] })
    return rowToInitiative(row)
  },

  async handoff(initiativeId: string): Promise<Initiative> {
    await init(); runSql("UPDATE initiatives SET state='FORMAL_HANDOFF_REQUIRED' WHERE id=?", [initiativeId])
    const r = exec('SELECT * FROM initiatives WHERE id=?', [initiativeId])
    if (!r[0]?.values[0]) throw new Error('Initiative not found')
    const c = r[0].columns; const row: Row = {}; c.forEach((col, i) => { row[col] = r[0].values[0][i] })
    return rowToInitiative(row)
  },

  async timeline(assetId: string): Promise<{ asset: { name: string; operational_state: string }; events: Array<Record<string, unknown>> }> {
    await init()
    const ar = exec('SELECT * FROM assets WHERE id=?', [assetId])
    if (!ar[0]?.values[0]) throw new Error('Asset not found')
    const ac = ar[0].columns, av = ar[0].values[0]
    const asset = { name: String(av[ac.indexOf('name')]), operational_state: String(av[ac.indexOf('operational_state')]) }
    const ir = exec('SELECT * FROM issues WHERE asset_id=? ORDER BY first_seen_at DESC', [assetId])
    const events: Array<Record<string, unknown>> = []
    if (ir[0]) ir[0].values.forEach((v) => { const c = ir[0].columns; events.push({ id: v[c.indexOf('id')], type: 'issue', title: v[c.indexOf('title')], state: v[c.indexOf('state')], date: v[c.indexOf('first_seen_at')] }) })
    return { asset, events }
  },

  async maxStatus() { return { mode: 'local', connected: false, api_connected: false, polling_active: false, transport: 'local' } },
  async validateMaxContext(_initData: string) { return { valid: true as const, user: { id: 1, first_name: 'Демо' }, chat: { id: 1, type: 'DIALOG' as const } } },
}
