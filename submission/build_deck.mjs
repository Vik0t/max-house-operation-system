import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const workspaceDir = path.resolve(process.cwd())
const skillDir = process.env.SKILL_DIR
const pythonExecutable = process.env.RUNTIME_PYTHON
const nodeModules = process.env.RUNTIME_NODE_MODULES
if (!skillDir || !pythonExecutable || !nodeModules) throw new Error('Set SKILL_DIR, RUNTIME_PYTHON and RUNTIME_NODE_MODULES')
const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(nodeModules, '@oai/artifact-tool/dist/artifact_tool.mjs')).href)
const buildDir = path.join(workspaceDir, 'submission/.build')
const finalPath = path.join(workspaceDir, 'submission/DomPuls_MAX_hackathon.pptx')
await fs.mkdir(buildDir, { recursive: true })
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir, 'container_tools/artifact_tool_utils.mjs')).href)

const pptx = Presentation.create({ slideSize: { width: 1280, height: 720 } })
const C = { ink: '#153049', muted: '#526575', blue: '#357FAB', pale: '#F6F8FA', white: '#FFFFFF', mint: '#D4E9E4', orange: '#E96F58' }
function text(slide, x, y, width, height, value, size = 28, color = C.ink, bold = false) {
  const shape = slide.shapes.add({ geometry: 'textbox', position: { left: x, top: y, width, height }, fill: 'none', line: { fill: 'none', width: 0 } })
  shape.text = value
  shape.text.style = { typeface: 'Arial', fontSize: size, color, bold, autoFit: 'none' }
  return shape
}
function base(title, number, dark = false) {
  const slide = pptx.slides.add()
  slide.background.fill = dark ? C.ink : C.pale
  if (number > 1) {
    text(slide, 70, 40, 650, 28, 'ДОМПУЛЬС   /   MAX', 18, dark ? C.mint : C.blue, true)
    text(slide, 70, 82, 1110, 90, title, 45, dark ? C.white : C.ink, true)
    text(slide, 1165, 660, 50, 25, String(number).padStart(2, '0'), 17, dark ? C.mint : C.muted)
  }
  return slide
}
async function mascot(slide, file, x, y, width, height) {
  slide.images.add({ blob: await fs.readFile(path.join(workspaceDir, 'apps/miniapp/public/mascot', file)), contentType: 'image/png', alt: 'Голубь Макс', fit: 'contain', position: { left: x, top: y, width, height } })
}
function note(slide, value) { slide.speakerNotes.textFrame.setText(value) }

{
  const slide = base('', 1, true)
  text(slide, 76, 78, 500, 50, 'ПРОЕКТ ДЛЯ ХАКАТОНА MAX', 21, C.mint, true)
  text(slide, 76, 174, 850, 130, 'ДомПульс', 82, C.white, true)
  text(slide, 80, 331, 820, 130, 'Сообщение жителя становится\nпроверенным результатом для дома', 34, C.white)
  text(slide, 80, 612, 820, 40, 'Бот MAX · мини-приложение · история объектов дома', 22, C.mint)
  await mascot(slide, 'max-04.png', 960, 266, 240, 254)
  note(slide, 'Основа: продуктовая спецификация MAX_DomPuls_Product_Technical_Spec_v3.md; README.md проекта.')
}
{
  const slide = base('Проблема повторяется. История теряется', 2)
  text(slide, 76, 228, 1090, 94, '«Лифт опять встал, второй подъезд»', 43, C.ink, true)
  text(slide, 76, 358, 880, 122, 'Жителю важно знать, что случилось с лифтом раньше, кто сейчас отвечает за работу и подтвердили ли соседи результат.', 29, C.muted)
  text(slide, 76, 541, 920, 65, 'Единица продукта — состояние лифта во времени.', 30, C.blue, true)
  await mascot(slide, 'max-01.png', 1000, 410, 205, 216)
  note(slide, 'Проблема и пример взяты из продуктовой спецификации. Не является результатом рыночного исследования.')
}
{
  const slide = base('Как работает замкнутый цикл', 3)
  const steps = [
    ['01', 'Сигналы', 'Сообщения жителей\nв личке и группе MAX'],
    ['02', 'Объект', 'Проблема лифта №2\nи прошлые инциденты'],
    ['03', 'Работа', 'Передача, исполнитель,\nфото выполнения'],
    ['04', 'Проверка', 'Житель подтвердил\nили открыл повторно'],
  ]
  steps.forEach(([n, label, body], i) => {
    const x = 74 + i * 300
    text(slide, x, 248, 245, 70, n, 52, i === 3 ? C.orange : C.blue, true)
    text(slide, x, 335, 255, 50, label, 30, C.ink, true)
    text(slide, x, 401, 255, 117, body, 23, C.muted)
  })
  text(slide, 76, 593, 1080, 46, 'После закрытия новая поломка видна как повторение на том же объекте.', 26, C.blue, true)
  note(slide, 'Реализовано: Signal, Issue, Action, Submission, WorkOrder, Evidence, Verification, Asset timeline. Тест: tests/e2e/test_golden_path.py.')
}
{
  const slide = base('У каждого участника своя задача', 4)
  const rows = [
    ['Житель', 'Сообщает о проблеме, подтверждает соседей, проверяет результат'],
    ['Домоуправляющий', 'Решает, готова ли проблема к передаче и кому адресовать'],
    ['УК', 'Принимает обращение и назначает работу'],
    ['Исполнитель', 'Выполняет работу и прикладывает подтверждение'],
  ]
  rows.forEach(([role, body], i) => {
    const y = 222 + i * 102
    text(slide, 76, y, 300, 48, role, 28, C.blue, true)
    text(slide, 394, y, 780, 73, body, 27, C.ink)
  })
  note(slide, 'Роли и доступы: README.md, docs/max_setup.md, apps/api/app/settings.py. В режиме показа роль можно переключать; для эксплуатации нужен allowlist MAX user_id.')
}
{
  const slide = base('MAX объединяет чат и состояние дома', 5)
  text(slide, 76, 221, 885, 110, 'Бот принимает сообщения группы и личного диалога. Мини-приложение открывает карточку дома и историю объекта.', 30, C.ink)
  text(slide, 76, 367, 830, 125, 'Инициатива жителей превращается в общий неформальный опрос прямо в групповом чате.', 29, C.blue, true)
  text(slide, 76, 547, 860, 76, 'MAX ID подтверждает аккаунт, но не факт проживания в доме.', 24, C.muted)
  await mascot(slide, 'max-09.png', 980, 336, 220, 176)
  note(slide, 'Реальная интеграция: MAX Bot API и MAX Bridge. Групповой опрос реализован и покрыт unit tests; живой групповой прогон требует тестового чата с ботом. Подробнее: docs/max_setup.md.')
}
{
  const slide = base('ML помогает, правила принимают решения', 6)
  text(slide, 76, 212, 450, 86, '92,86%', 70, C.blue, true)
  text(slide, 76, 306, 450, 78, 'точность категории\nна отложенной выборке', 25, C.muted)
  text(slide, 576, 212, 450, 86, '0,9317', 70, C.blue, true)
  text(slide, 576, 306, 450, 78, 'macro-F1\nна той же выборке', 25, C.muted)
  text(slide, 76, 447, 1010, 118, 'Категория определяется локально. Место, объект, дубликат и повторяемость проходят отдельную проверку; при сомнении бот уточняет только недостающий факт.', 27, C.ink)
  text(slide, 76, 615, 1110, 32, 'Выборка из 350 подготовленных сообщений; оценка не заменяет проверку на реальных чатах.', 20, C.muted)
  note(slide, 'Метрики: reports/category_eval.json и docs/ai_metrics.md. Внешний OpenRouter получает только текст, который пользователь вручную пишет помощнику, с согласия пользователя.')
}
{
  const slide = base('Проверяемость и границы MVP', 7)
  text(slide, 76, 217, 520, 57, '2 дома', 44, C.blue, true)
  text(slide, 76, 283, 500, 91, 'Разная конфигурация объектов, маршрутов и порогов повторяемости', 25, C.ink)
  text(slide, 655, 217, 510, 57, '100+ тестов', 44, C.blue, true)
  text(slide, 655, 283, 500, 91, 'В том числе 20 последовательных прогонов основного сценария', 25, C.ink)
  text(slide, 76, 446, 1080, 138, 'Передача в УК и государственные системы пока учебная. Данные демо-истории помечены как синтетические. Неформальный опрос не является ОСС.', 28, C.ink)
  note(slide, 'Проверка: README.md, configs/demo_house_a.yaml, configs/demo_house_b.yaml, tests/. Статус интеграций и ограничения перечислены в README.md и docs/evidence_registry.md.')
}
{
  const slide = base('Демонстрация за четыре минуты', 8, true)
  const items = [
    '1  Три сообщения о лифте во втором подъезде',
    '2  Одна проблема: подтверждения и четвёртый случай',
    '3  Передача, назначение, фото работы',
    '4  Житель подтверждает: лифт работает',
    '5  История лифта обновилась; опрос по освещению открыт',
    '6  Второй дом показывает иную конфигурацию',
  ]
  items.forEach((item, i) => text(slide, 76, 205 + i * 62, 1100, 51, item, 27, C.white, i === 3))
  text(slide, 76, 619, 1070, 37, 'MAX: @t312_hakaton_max_bot     Мини-приложение: apaww.github.io/dom.sreda.io', 22, C.mint)
  note(slide, 'Точный сценарий: docs/demo.md. Бот использует реальный MAX Bot API. Внешняя отправка в УК симулируется и явно отмечена в интерфейсе.')
}

const stagingDir = path.join(workspaceDir, '.codex-finalizer')
await fs.mkdir(stagingDir, { recursive: true })
const candidatePath = path.join(stagingDir, 'candidate.pptx')
await (await PresentationFile.exportPptx(pptx)).save(candidatePath)
for (let i = 0; i < pptx.slides.items.length; i++) {
  const preview = await pptx.export({ slide: pptx.slides.items[i], format: 'png', scale: 1 })
  await fs.writeFile(path.join(buildDir, `slide-${i + 1}.png`), new Uint8Array(await preview.arrayBuffer()))
}
const result = await finalizePresentation({
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable,
  integrityValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-heading-fit'],
  fontPolicy: { basis: 'design', families: ['Arial'] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, 'DomPuls_MAX_hackathon.validation-v3.json'),
})
console.log(JSON.stringify({ finalPath, result }))
