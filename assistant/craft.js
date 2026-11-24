/**
 * PyMCL AI 助手 —— 自动收集材料并合成。
 * 「帮我做钻石剑」流程：配方展开（递归中间材料）→ 库存清点 → 附近箱子取料 →
 * 挖矿收集（mineflayer-collectblock）→ 合成中间物与成品（自动找/放工作台）→
 * 走到玩家身边扔出成品。
 * 已知边界：需要熔炼的材料（铁锭等）与模组物品无法自动获取，会明确告知。
 */
'use strict';
const { goals } = require('mineflayer-pathfinder');
const { Vec3 } = require('vec3');
const { displayOf } = require('./recipes');

const CRAFT_TYPES = new Set(['crafting_shaped', 'crafting_shapeless']);
const MAX_DEPTH = 6;
const MAX_STEPS = 24;

// 可直接挖到的基础材料 → 可开采的方块名
const HARVEST = new Map(Object.entries({
  cobblestone: ['stone', 'cobbled_deepslate'],
  oak_log: ['oak_log'], spruce_log: ['spruce_log'], birch_log: ['birch_log'],
  jungle_log: ['jungle_log'], acacia_log: ['acacia_log'], dark_oak_log: ['dark_oak_log'],
  cherry_log: ['cherry_log'], mangrove_log: ['mangrove_log'],
  diamond: ['diamond_ore', 'deepslate_diamond_ore'],
  coal: ['coal_ore', 'deepslate_coal_ore'],
  raw_iron: ['iron_ore', 'deepslate_iron_ore'],
  raw_copper: ['copper_ore', 'deepslate_copper_ore'],
  raw_gold: ['gold_ore', 'deepslate_gold_ore', 'nether_gold_ore'],
  redstone: ['redstone_ore', 'deepslate_redstone_ore'],
  lapis_lazuli: ['lapis_ore', 'deepslate_lapis_ore'],
  emerald: ['emerald_ore', 'deepslate_emerald_ore'],
  sand: ['sand'], dirt: ['dirt'], gravel: ['gravel'], netherrack: ['netherrack'],
  clay_ball: ['clay'], snowball: ['snow_block'],
}));

function isSmeltOnly(name) {
  return [
    'iron_ingot', 'gold_ingot', 'copper_ingot', 'netherite_scrap', 'netherite_ingot',
    'cooked_beef', 'cooked_porkchop', 'cooked_chicken', 'cooked_cod', 'cooked_salmon',
    'baked_potato', 'glass', 'smooth_stone', 'charcoal', 'brick', 'nether_brick',
    'stone', 'dried_kelp_block',
  ].includes(name);
}

// ---------------- 计划展开（纯函数，可单测） ----------------
/**
 * index: recipes.buildIndex() 结果；name/count: 目标物品与数量。
 * 返回 { ok, steps, needs, blocked }
 *   steps:  依赖序的合成步骤 [{name, times}]（先中间物后成品）
 *   needs:  基础材料 Map<name, count>（无法合成的叶子）
 *   blocked: Set<name> 需要熔炼、无法自动获取
 */
function computePlan(index, name, count) {
  const stepCrafts = new Map(); // name -> 需要合成几次
  const needs = new Map();      // base material -> count
  const blocked = new Set();

  const occurrences = (plan) => {
    const out = [];
    if (plan.shape) {
      for (const row of plan.shape) for (const c of row) if (c && !c.startsWith('tag:')) out.push(c);
    }
    if (plan.ingredients) {
      for (const c of plan.ingredients) if (c && !c.startsWith('tag:')) out.push(c);
    }
    return out;
  };

  const expand = (item, needCount, depth) => {
    // 可开采的（钻石/原木/圆石）与熔炼产物（铁锭/金锭/玻璃等）一律当基础材料：
    // 前者直接挖，后者不会合成（原版的「铁块→9铁锭」反向配方是无意义链条）
    if (HARVEST.has(item) || isSmeltOnly(item) ||
        depth >= MAX_DEPTH || stepCrafts.size > MAX_STEPS) {
      needs.set(item, (needs.get(item) || 0) + needCount);
      return;
    }
    const plan = index.planOf(item);
    const craftable = plan && CRAFT_TYPES.has(plan.type);
    if (!craftable) {
      if (plan) blocked.add(item);   // 只有熔炼/切割配方
      needs.set(item, (needs.get(item) || 0) + needCount);
      return;
    }
    if (stepCrafts.has(item)) {      // 环路守卫：已在合成链中的物品不再展开
      needs.set(item, (needs.get(item) || 0) + needCount);
      return;
    }
    const yieldPer = plan.count || 1;
    const crafts = Math.ceil(needCount / yieldPer);
    stepCrafts.set(item, (stepCrafts.get(item) || 0) + crafts);
    // 先聚合本配方各原料的总需求量，再逐个展开（避免同一原料按次数重复展开）
    const agg = new Map();
    for (const ing of occurrences(plan)) agg.set(ing, (agg.get(ing) || 0) + crafts);
    for (const [ing, total] of agg) expand(ing, total, depth + 1);
  };

  expand(name, count, 0);
  // 插入序是父先于子，反转后即“先中间物后成品”，目标自然排最后
  const steps = [...stepCrafts.entries()].reverse()
    .map(([n, times]) => ({ name: n, times }));
  return { ok: true, steps, needs, blocked: [...blocked] };
}

// ---------------- 执行辅助 ----------------
function invCount(bot, name) {
  return bot.inventory.items().filter((i) => i.name === name)
    .reduce((a, i) => a + i.count, 0);
}

async function gotoNear(bot, pos, range = 2) {
  await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, range));
}

async function collectBlocks(bot, block, count) {
  const cb = bot.collectBlock;
  if (typeof cb === 'function') return cb.call(bot, block, count);      // 旧 API（≤1.3）
  if (cb && typeof cb.collect === 'function') return cb.collect(block, count); // 1.6+ 实例
  throw new Error('collectblock 插件不可用');
}

async function withdrawFromChests(bot, mcData, needs, say, log = () => {}) {
  const chestNames = ['chest', 'trapped_chest', 'barrel'];
  const chestIds = chestNames.map((n) => mcData.blocksByName[n])
    .filter(Boolean).map((b) => b.id);
  let found = bot.findBlocks({ matching: chestIds, maxDistance: 16, count: 8 }) || [];
  if (!found.length) {
    // 部分协议版本下按数字 id 匹配会失灵，退回按方块名匹配
    found = bot.findBlocks({
      matching: (b) => chestNames.includes(b.name),
      maxDistance: 16, count: 8,
    }) || [];
  }
  if (!found.length) { say('附近 16 格没找到箱子，把材料放箱子或丢给我也行'); return; }
  log(`箱子搜索: 命中 ${found.length} 个容器，坐标 ${found.map((p) => `${p.x},${p.y},${p.z}`).join(' | ')}`);
  for (const pos of found) {
    let remaining = [...needs.entries()].some(([n, c]) => c > invCount(bot, n));
    if (!remaining) break;
    try {
      await gotoNear(bot, pos, 2);
      const chest = await bot.openChest(bot.blockAt(pos));
      for (const [name, need] of [...needs.entries()]) {
        let short = need - invCount(bot, name);
        if (short <= 0) continue;
        // mineflayer 4.x 的 openChest 返回 Window：items() 是背包侧，
        // 箱子内容在 containerItems()；shift+左键（mode 1）由服务端移入背包。
        // 背包同步包延迟不可靠，取物量以箱子侧该组消失为准
        let taken = 0;
        for (let guard = 0; guard < 27 && short > 0; guard++) {
          const stack = (chest.containerItems() || []).find((i) => i.name === name);
          if (!stack) break;
          await bot.clickWindow(stack.slot ?? 0, 0, 1);
          let gone = false;
          for (let wait = 0; wait < 8; wait++) {
            await new Promise((r) => setTimeout(r, 250));
            if (!(chest.containerItems() || []).some((i) => i.name === name)) {
              gone = true;
              break;
            }
          }
          if (!gone) break;   // 这组没取到，防死循环
          taken += stack.count;
          short -= stack.count;
        }
        if (taken > 0) say(`从箱子里取了 ${taken} 个${displayOf(name)}`);
      }
      chest.close();
    } catch (e) {
      say(`有个箱子打不开（${String(e.message).slice(0, 30)}），换下一个试试`);
    }
  }
}

async function mineMissing(bot, mcData, needs, say) {
  for (const [name, need] of [...needs.entries()]) {
    const short = need - invCount(bot, name);
    if (short <= 0) continue;
    const blocks = HARVEST.get(name);
    if (!blocks) continue;
    for (const blockName of blocks) {
      const blockType = mcData.blocksByName[blockName];
      if (!blockType) continue;
      try {
        say(`附近找找 ${displayOf(blockName)}，需要再挖 ${short} 个…`);
        // 1.6 API 的 collect() 要真实 Block 实例，先在附近找
        const found = bot.findBlock({ matching: blockType.id, maxDistance: 48 });
        if (!found) continue;
        await collectBlocks(bot, found, short);
        break;
      } catch (e) {
        if (/no blocks? (found|to collect)/i.test(e.message)) continue;
        say(`挖 ${displayOf(blockName)} 时出了点状况: ${String(e.message).slice(0, 40)}`);
      }
    }
  }
}

async function ensureCraftingTable(bot, mcData, say) {
  const table = bot.findBlock({ matching: mcData.blocksByName.crafting_table.id, maxDistance: 16 });
  if (table) {
    await gotoNear(bot, table.position, 2);
    return table;
  }
  if (invCount(bot, 'crafting_table') > 0) {
    const base = bot.entity.position.floored();
    for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const target = base.offset(dx, 0, dz);
      const ground = bot.blockAt(target.offset(0, -1, 0));
      const at = bot.blockAt(target);
      if (ground && (!at || at.boundingBox === 'empty')) {
        await bot.equip(mcData.itemsByName.crafting_table.id, 'hand');
        await bot.placeBlock(ground, new Vec3(0, 1, 0));
        say('放了个工作台');
        await new Promise((r) => setTimeout(r, 400));
        const placed = bot.blockAt(target);
        if (placed && placed.name === 'crafting_table') return placed;
        break;
      }
    }
  }
  throw new Error('附近没有工作台，我包里也没能放一个');
}

async function craftWithFallback(bot, mcData, name, times, table) {
  const item = mcData.itemsByName[name];
  if (!item) throw new Error(`未知物品 ${name}`);
  const recipes = bot.recipesFor(item.id, null, 1, table);
  for (const r of recipes) {
    try {
      await bot.craft(r, times, table);
      return;
    } catch (e) {
      if (!/missing|材料|requirements/i.test(e.message)) throw e;
    }
  }
  throw new Error(`合成 ${name} 材料不足`);
}

async function tossToPlayer(bot, mcData, name, username, say) {
  const p = bot.players[username];
  if (p && p.entity) {
    try {
      await gotoNear(bot, p.entity.position, 2);
      await bot.lookAt(p.entity.position.offset(0, 1, 0));
    } catch (_) { /* 走不过去就直接扔 */ }
  }
  const stack = bot.inventory.items().find((i) => i.name === name);
  if (stack) {
    await bot.tossStack(stack);
    say(`做好了，${username} 拿好～`);
  } else {
    say(`做好的 ${displayOf(name)} 在我背包里（可能被拿走了），跟我说一声我再给`);
  }
}

// ---------------- 主流程 ----------------
async function handleCraft(bot, username, itemName, ctx) {
  const { say, sayChunks, index, log } = ctx;
  if (!index) { say('配方库还在加载，几秒后再叫我～'); return; }

  const ids = index.findIds(itemName);
  const targetId = ids[0];
  if (!targetId) { say(`不知道「${itemName}」是什么东西，说个英文名试试？`); return; }
  if (targetId.includes(':') && !targetId.startsWith('minecraft:')) {
    sayChunks(`「${targetId}」是模组物品，我的客户端是原版协议，合成不了它呢（需要原版物品）`);
    return;
  }

  const mcData = require('minecraft-data')(bot.version);
  if (!mcData.itemsByName[targetId.replace('minecraft:', '')]) {
    sayChunks(`「${targetId}」我合成不了（原版 ${bot.version} 里没有）`);
    return;
  }

  const count = Math.max(1, Math.min(8, (itemName.match(/(\d+)/) || [0, 1])[1] | 0));
  const plan = computePlan(index, targetId, count);
  const needsText = [...plan.needs.entries()]
    .map(([n, c]) => `${displayOf(n)} x${c}`).join('、');
  say(`好的，开始做 ${count} 个${displayOf(targetId)}！需要基础材料: ${needsText}` +
    (plan.blocked.length ? `（另外这些我做不了: ${plan.blocked.join('、')}，需要熔炼）` : ''));

  // 短缺清点（扣除已有库存）
  const missing = new Map();
  for (const [n, c] of plan.needs.entries()) {
    const short = c - invCount(bot, n);
    if (short > 0) missing.set(n, short);
  }
  if (missing.size) {
    await withdrawFromChests(bot, mcData, missing, say, log);
    await mineMissing(bot, mcData, missing, say);
  }

  const stillShort = [...plan.needs.entries()]
    .filter(([n, c]) => c > invCount(bot, n))
    .map(([n, c]) => `${displayOf(n)} 缺 ${c - invCount(bot, n)}` +
      (isSmeltOnly(n) ? '（要熔炼，我不会）' : ''));
  if (stillShort.length) {
    sayChunks(`材料不够，做不了: ${stillShort.join('、')}。` +
      '把材料放附近箱子或丢给我，再叫我一次就好');
    return;
  }

  say('材料齐了，开始合成！');
  for (const step of plan.steps) {
    try {
      const table = await ensureCraftingTable(bot, mcData, say);
      await craftWithFallback(bot, mcData, step.name.replace('minecraft:', ''), step.times, table);
      say(`合成 ${displayOf(step.name)} x${step.times} ✓`);
    } catch (e) {
      log(`制作 ${step.name} 失败: ${e.message}`);
      sayChunks(`卡在「${displayOf(step.name)}」: ${e.message}`);
      return;
    }
  }
  await tossToPlayer(bot, mcData, targetId.replace('minecraft:', ''), username, say);
}

module.exports = { handleCraft, computePlan };
