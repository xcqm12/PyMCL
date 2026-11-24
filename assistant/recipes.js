/**
 * PyMCL AI 助手 —— 配方知识库。
 * 原版配方来自 minecraft-data（随 mineflayer 安装）；模组配方从 mods 目录的
 * jar 包里解析 data/<ns>/recipe(s)/*.json（1.13+ 数据包格式）。
 * 提供中文关键词检索（常用物品内置词典）与「X 能做什么」反查。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');

// ---------------- 常用原版物品中文词典（查询匹配用） ----------------
const ZH_ITEMS = {
  '钻石': 'diamond', '钻石剑': 'diamond_sword', '钻石镐': 'diamond_pickaxe',
  '钻石斧': 'diamond_axe', '钻石锹': 'diamond_shovel', '钻石锄': 'diamond_hoe',
  '钻石头盔': 'diamond_helmet', '钻石胸甲': 'diamond_chestplate',
  '钻石护腿': 'diamond_leggings', '钻石靴子': 'diamond_boots',
  '下界合金锭': 'netherite_ingot', '下界合金剑': 'netherite_sword',
  '下界合金镐': 'netherite_pickaxe', '下界合金斧': 'netherite_axe',
  '下界合金锹': 'netherite_shovel', '下界合金头盛': 'netherite_helmet',
  '下界合金头盃': 'netherite_helmet', '下界合金胸甲': 'netherite_chestplate',
  '合金升级': 'netherite_upgrade_smithing_template',
  '铁锭': 'iron_ingot', '铁剑': 'iron_sword', '铁镐': 'iron_pickaxe',
  '铁斧': 'iron_axe', '铁锹': 'iron_shovel', '铁头盃': 'iron_helmet',
  '铁胸甲': 'iron_chestplate', '铁护腿': 'iron_leggings', '铁靴子': 'iron_boots',
  '铁块': 'iron_block', '铁砧': 'anvil', '铁轨': 'rail',
  '充能铁轨': 'powered_rail', '探测铁轨': 'detector_rail', '矿车': 'minecart',
  '金锭': 'gold_ingot', '金剑': 'gold_sword', '金镐': 'gold_pickaxe',
  '金块': 'gold_block', '金萝卜': 'golden_carrot', '金苹果': 'golden_apple',
  '铜锭': 'copper_ingot', '铜块': 'copper_block',
  '木棍': 'stick', '木板': 'planks', '橡木板': 'oak_planks', '木头': 'oak_log',
  '工作台': 'crafting_table', '熔炉': 'furnace', '高炉': 'blast_furnace',
  '烟熏炉': 'smoker', '切石机': 'stonecutter', '锻造台': 'smithing_table',
  '砂轮': 'grindstone', '织布机': 'loom', '制图台': 'cartography_table',
  '石剑': 'stone_sword', '石镐': 'stone_pickaxe', '石斧': 'stone_axe',
  '木剑': 'wooden_sword', '木镐': 'wooden_pickaxe',
  '圆石': 'cobblestone', '石头': 'stone', '深板岩': 'deepslate',
  '石砖': 'stone_bricks', '平滑石': 'smooth_stone', '泥土': 'dirt', '沙子': 'sand',
  '砂砾': 'gravel', '玻璃': 'glass', '玻璃板': 'glass_pane',
  '煤炭': 'coal', '煤块': 'coal_block', '木炭': 'charcoal',
  '红石': 'redstone', '红石块': 'redstone_block', '红石火把': 'redstone_torch',
  '红石中继器': 'repeater', '红石比较器': 'comparator',
  '青金石': 'lapis_lazuli', '绿宝石': 'emerald', '石英': 'quartz',
  '火把': 'torch', '简灯': 'lantern', '灯笼': 'lantern',
  '活塞': 'piston', '粘性活塞': 'sticky_piston', '观察者': 'observer',
  '投掷器': 'dropper', '发射器': 'dispenser', '漏斗': 'hopper',
  '箱子': 'chest', '陷阱箱': 'trapped_chest', '末影箱': 'ender_chest',
  '木桶': 'barrel', '盔甲架': 'armor_stand', '物品展示框': 'item_frame',
  '梯子': 'ladder', '告示牌': 'oak_sign', '门': 'oak_door', '活板门': 'oak_trapdoor',
  '栅栏': 'oak_fence', '栅栏门': 'oak_fence_gate',
  '弓': 'bow', '箭': 'arrow', '盾牌': 'shield', '剪刀': 'shears',
  '钓鱼竿': 'fishing_rod', '打火石': 'flint_and_steel', 'TNT': 'tnt',
  '末影珍珠': 'ender_pearl', '末影之眼': 'ender_eye', '烈焰棒': 'blaze_rod',
  '烈焰粉': 'blaze_powder', '恶魂之泪': 'ghast_tear', '下界之星': 'nether_star',
  '鞘翅': 'elytra', '三叉戟': 'trident', '经验瓶': 'experience_bottle',
  '附魔台': 'enchanting_table', '书架': 'bookshelf', '书': 'book', '纸': 'paper',
  '指南针': 'compass', '时钟': 'clock', '地图': 'map', '床': 'white_bed',
  '面包': 'bread', '小麦': 'wheat', '小麦种子': 'wheat_seeds', '苹果': 'apple',
  '胡萝卜': 'carrot', '马鈴薯': 'potato', '土豆': 'potato', '烤土豆': 'baked_potato',
  '牛排': 'cooked_beef', '生牛肉': 'beef', '熟猪排': 'cooked_porkchop',
  '生猪排': 'porkchop', '熟鸡肉': 'cooked_chicken', '生鸡肉': 'chicken',
  '鳕鱼': 'cod', '三文鱼': 'salmon', '蛋糕': 'cake', '曲奇': 'cookie',
  '南瓜派': 'pumpkin_pie', '蘑菇煲': 'mushroom_stew', '糖': 'sugar',
  '鸡蛋': 'egg', '牛奶': 'milk_bucket', '皮革': 'leather',
  '玻璃瓶': 'glass_bottle', '炼药锅': 'cauldron', '岩浆膏': 'magma_cream',
};

const ZH_TYPES = {
  crafting_shaped: '工作台有序合成', crafting_shapeless: '工作台无序合成',
  smelting: '熔炉烧炼', blasting: '高炉熔炼', smoking: '烟熏炉熏制',
  campfire_cooking: '营火烹饪', stonecutting: '切石机切割',
};

// 反查表：英文尾名 → 中文名
const ZH_DISPLAY = {};
for (const [zh, tail] of Object.entries(ZH_ITEMS)) {
  if (!(tail in ZH_DISPLAY)) ZH_DISPLAY[tail] = zh;
}

// ---------------- 工具 ----------------
function displayOf(id) {
  if (!id) return '空';
  const tail = String(id).split(':').pop();
  return ZH_DISPLAY[tail] || tail.replace(/_/g, ' ');
}
function typeLabel(type) {
  return ZH_TYPES[type] || type || '合成';
}

/** 在查询里找中文词典命中的英文尾名（长词优先）。 */
function zhToTail(q) {
  const keys = Object.keys(ZH_ITEMS).sort((a, b) => b.length - a.length);
  const ql = q.toLowerCase();
  for (const k of keys) if (ql.includes(k.toLowerCase())) return ZH_ITEMS[k];
  return null;
}

function ingOf(x) {
  if (x == null) return null;
  if (Array.isArray(x)) return x.map(ingOf);
  if (typeof x === 'string') return x;
  if (x.tag) return 'tag:' + x.tag;        // 打标签前缀，与物品 id 区分
  return x.item || x.id || null;
}

// ---------------- 原版配方（minecraft-data） ----------------
function loadVanilla(mcVersion) {
  const mcData = require('minecraft-data')(mcVersion);
  const out = [];
  const recipes = mcData.recipes || {};
  for (const entries of Object.values(recipes)) {
    for (const r of entries) {
      if (!r || !r.result) continue;
      const item = mcData.items[r.result.id];
      if (!item) continue;
      let shape = null;
      let ingredients = null;
      if (Array.isArray(r.inShape)) {
        shape = r.inShape.map((row) =>
          (Array.isArray(row) ? row : [row]).map((cell) =>
            cell == null ? null : (mcData.items[cell] ? mcData.items[cell].name : null)));
      } else if (Array.isArray(r.ingredients)) {
        ingredients = r.ingredients.map((cell) =>
          (Array.isArray(cell) ? cell.map((c) => mcData.items[c] ? mcData.items[c].name : null)
            : (mcData.items[cell] ? mcData.items[cell].name : null)));
      }
      if (!shape && !ingredients) continue;
      out.push({
        type: shape ? 'crafting_shaped' : 'crafting_shapeless',
        out: item.name, count: r.result.count || 1,
        shape, ingredients, source: 'vanilla',
      });
    }
  }
  return out;
}

// ---------------- 模组配方（扫描 mods 目录里的 jar） ----------------
const RECIPE_PATH_RE = /^data\/([^/]+)\/recipe(?:s)?\/.+\.json$/;

function loadModJar(file, push) {
  let zip;
  try {
    zip = new AdmZip(file);
  } catch (_) {
    return 0;
  }
  let n = 0;
  for (const entry of zip.getEntries()) {
    const name = entry.entryName.replace(/\\/g, '/');
    const m = RECIPE_PATH_RE.exec(name);
    if (!m || entry.isDirectory) continue;
    let j;
    try {
      j = JSON.parse(entry.getData().toString('utf8'));
    } catch (_) {
      continue;
    }
    const ns = m[1];
    const type = String(j.type || '').replace('minecraft:', '');
    const res = j.result || {};
    const out = (typeof res === 'string') ? res : (res.item || res.id || null);
    if (!out || typeof out !== 'string') continue;
    const count = (typeof res === 'object' && res.count) || 1;
    let shape = null;
    let ingredients = null;
    if (type === 'crafting_shaped' && Array.isArray(j.pattern)) {
      const key = j.key || {};
      shape = j.pattern.map((row) => [...String(row)].map((ch) => {
        if (ch === ' ') return null;                    // 空格子，合法
        if (!(ch in key)) return '\u0000invalid';       // key 里没有该符号，整条作废
        return ingOf(key[ch]);
      }));
      if (shape.some((row) => row.some((c) =>
        c === '\u0000invalid' || (c != null && typeof c !== 'string')))) shape = null;
    } else if (type === 'crafting_shapeless' && Array.isArray(j.ingredients)) {
      ingredients = j.ingredients.map(ingOf).flat(2);
      if (ingredients.some((c) => c == null)) ingredients = null;
    } else if (['smelting', 'blasting', 'smoking', 'campfire_cooking', 'stonecutting'].includes(type)) {
      const i0 = ingOf(j.ingredient);
      ingredients = (Array.isArray(i0) ? i0 : [i0]).flat(2);
      if (ingredients.some((c) => c == null)) ingredients = null;
    } else {
      continue;
    }
    if (!shape && !ingredients) continue;
    push({ type, out, count, shape, ingredients, source: 'mod', ns });
    n += 1;
  }
  return n;
}

function loadMods(modsDirs, log) {
  const out = [];
  let jars = 0;
  for (const dir of modsDirs || []) {
    let files = [];
    try {
      files = fs.readdirSync(dir).filter((f) =>
        f.endsWith('.jar') && !f.endsWith('.jar.disabled') && !f.includes('-sources'));
    } catch (_) {
      continue;
    }
    for (const f of files) {
      try {
        jars += 1;
        loadModJar(path.join(dir, f), (r) => out.push(r));
      } catch (e) {
        if (log) log(`模组配方解析失败 ${f}: ${e.message}`);
      }
    }
  }
  return { recipes: out, jars };
}

// ---------------- 索引与检索 ----------------
function recipeText(r) {
  const label = typeLabel(r.type);
  const disp = (c) => c == null ? '空'
    : (typeof c === 'string' && c.startsWith('tag:') ? '标签:' + c.slice(4) : displayOf(c));
  let body;
  if (r.shape) {
    body = r.shape.map((row) => row.map(disp).join(' ')).join(' / ');
    body = `${r.shape.length}行摆法: ${body}`;
  } else if (r.type === 'stonecutting' || ['smelting', 'blasting', 'smoking', 'campfire_cooking'].includes(r.type)) {
    body = `${(r.ingredients || []).map(disp).join(' 或 ')} → ${displayOf(r.out)}`;
  } else {
    body = (r.ingredients || []).map(disp).join(' + ');
  }
  const src = r.source === 'mod' ? ` [模组:${r.ns}]` : '';
  const cnt = r.count > 1 ? ` x${r.count}` : '';
  return `${label}（${displayOf(r.out)}${cnt}）: ${body}${src}`;
}

function buildIndex({ mcVersion, modsDirs, log } = {}) {
  const byResult = new Map();   // out id -> [recipe]
  const byIngredient = new Map(); // ingredient id -> Set(out id)
  const allIds = new Set();
  let vanillaN = 0;
  let modN = 0;
  let jars = 0;

  const push = (r) => {
    if (!byResult.has(r.out)) byResult.set(r.out, []);
    byResult.get(r.out).push(r);
    allIds.add(r.out);
    const ings = new Set();
    for (const row of (r.shape || [])) for (const c of row) if (c) ings.add(c);
    for (const c of (r.ingredients || [])) if (c) ings.add(c);
    for (const c of ings) {
      if (typeof c !== 'string' || c.startsWith('tag:')) continue; // 标签不进反查
      if (!byIngredient.has(c)) byIngredient.set(c, new Set());
      byIngredient.get(c).add(r.out);
    }
    if (r.source === 'vanilla') vanillaN += 1; else modN += 1;
  };

  if (mcVersion) {
    try {
      for (const r of loadVanilla(mcVersion)) push(r);
    } catch (e) {
      if (log) log(`原版配方加载失败(${mcVersion}): ${e.message}`);
    }
  }
  const mods = loadMods(modsDirs, log);
  jars = mods.jars;
  for (const r of mods.recipes) push(r);

  function findIds(q) {
    const ql = q.toLowerCase().replace(/\s+/g, '');
    const tail = zhToTail(q) || null;
    const scored = [];
    for (const id of allIds) {
      const idl = id.toLowerCase();
      const tailName = idl.split(':').pop();
      let score = 0;
      if (tail && tailName === tail) score = 100;
      else if (tail && tailName.includes(tail)) score = 80;
      else if (idl === ql || tailName === ql) score = 90;
      else if (tailName.includes(ql) || idl.includes(ql)) score = 50;
      else if (ql.length >= 3 && tailName.replace(/_/g, '').includes(ql.replace(/_/g, ''))) score = 40;
      if (score) scored.push({ id, score });
    }
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, 3).map((s) => s.id);
  }

  return {
    counts: { vanilla: vanillaN, mod: modN, jars },
    findIds,
    recipesOf(id, limit = 2) {
      return (byResult.get(id) || []).slice(0, limit).map(recipeText);
    },
    planOf(id) {
      // 返回该物品首个可合成（crafting）配方的原始结构，供自动制作展开；
      // 若只有熔炼/切割类配方也返回（调用方自行拒绝），无配方返回 null
      const list = byResult.get(id) || [];
      return list.find((r) => r.type === 'crafting_shaped' || r.type === 'crafting_shapeless')
        || list[0] || null;
    },
    search(q) {
      const ids = findIds(q);
      return ids.map((id) => ({
        id,
        display: displayOf(id),
        lines: this.recipesOf(id),
      }));
    },
    usesOf(q, limit = 8) {
      const ids = findIds(q);
      const outs = new Set();
      for (const id of ids) {
        for (const o of byIngredient.get(id) || []) {
          if (o !== ids[0]) outs.add(o);
        }
      }
      return [...outs].slice(0, limit).map((o) => displayOf(o));
    },
  };
}

module.exports = { buildIndex, displayOf, zhToTail, recipeText };
