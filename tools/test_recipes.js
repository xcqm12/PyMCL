/** recipes.js 单元测试：原版索引 + 模拟模组 jar 解析 + 中文检索 + 反查 */
'use strict';
const fs = require('fs');
const path = require('path');
const AdmZip = require('F:/936/.minecraft/assistant/node_modules/adm-zip');
const recipes = require('F:/936/.minecraft/assistant/recipes.js');

let failed = 0;
function check(name, cond, extra = '') {
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${extra ? ' | ' + extra : ''}`);
  if (!cond) failed += 1;
}

// ---- 1. 合成模拟模组 jar（shaped / smelting / shapeless+tag） ----
const modDir = path.join(__dirname, 'fake_mods');
fs.mkdirSync(modDir, { recursive: true });
const zip = new AdmZip();
zip.addFile('data/testmod/recipes/magic_wand.json', JSON.stringify({
  type: 'minecraft:crafting_shaped',
  pattern: [' D', ' S ', 'S  '],
  key: { D: { item: 'minecraft:diamond' }, S: { item: 'testmod:magic_stick' } },
  result: { item: 'testmod:magic_wand', count: 1 },
}));
zip.addFile('data/testmod/recipes/magic_ingot.json', JSON.stringify({
  type: 'minecraft:smelting',
  ingredient: { tag: 'forge:ores/magic' },
  result: { item: 'testmod:magic_ingot' },
  experience: 1,
}));
zip.addFile('data/testmod/recipes/magic_stick.json', JSON.stringify({
  type: 'minecraft:crafting_shapeless',
  ingredients: [{ item: 'minecraft:stick' }, { item: 'minecraft:lapis_lazuli' }],
  result: { item: 'testmod:magic_stick' },
}));
zip.addFile('assets/testmod/lang/zh_cn.json', JSON.stringify({}));
zip.writeZip(path.join(modDir, 'testmod-1.0.jar'));

// ---- 2. 构建索引（原版 1.20.1 + 模拟模组） ----
const idx = recipes.buildIndex({
  mcVersion: '1.20.1',
  modsDirs: [modDir],
  log: (m) => console.log('[log]', m),
});
console.log(`索引: 原版 ${idx.counts.vanilla} 条, 模组 ${idx.counts.mod} 条, jar ${idx.counts.jars} 个`);
check('原版配方数量 > 300', idx.counts.vanilla > 300, String(idx.counts.vanilla));
check('模组配方数量 >= 3', idx.counts.mod >= 3, String(idx.counts.mod));
check('扫描到 1 个 jar', idx.counts.jars === 1);

// ---- 3. 中文检索：钻石剑 ----
const s1 = idx.search('怎么做钻石剑'.replace(/^怎么做/, '') || '钻石剑');
const sword = idx.search('钻石剑');
check('中文「钻石剑」命中 diamond_sword',
  sword.some((m) => m.id.endsWith('diamond_sword')),
  JSON.stringify(sword.map((m) => m.id)));
const swordRecipe = sword.find((m) => m.id.endsWith('diamond_sword'));
check('钻石剑配方文本含摆法与材料',
  swordRecipe && /钻石/.test(swordRecipe.lines.join('')) && /摆法/.test(swordRecipe.lines.join('')),
  swordRecipe ? swordRecipe.lines[0].slice(0, 80) : '');

// ---- 4. 反查：钻石能做什么 ----
const uses = idx.usesOf('钻石');
check('「钻石」反查含钻石剑', uses.includes('钻石剑'), uses.slice(0, 5).join('、'));

// ---- 5. 模组配方解析 ----
const wand = idx.search('magic_wand');
check('英文 id 检索模组物品 magic_wand', wand.some((m) => m.id === 'testmod:magic_wand'),
  JSON.stringify(wand.map((m) => m.id)));
const wandR = wand.find((m) => m.id === 'testmod:magic_wand');
check('模组 shaped 配方保留标签/物品', wandR && /magic stick/.test(wandR.lines.join('')),
  wandR ? wandR.lines[0].slice(0, 80) : '');
const ingot = idx.search('magic_ingot');
check('模组 smelting 配方带标签描述',
  ingot.some((m) => /标签/.test(m.lines.join(''))),
  ingot.length ? ingot[0].lines[0].slice(0, 80) : '');

// ---- 6. 英文模糊检索 ----
const fuzzy = idx.search('diamondpick');
check('英文模糊检索 diamondpick → 钻石镐',
  fuzzy.some((m) => m.id.endsWith('diamond_pickaxe')));

process.exit(failed ? 1 : 0);
