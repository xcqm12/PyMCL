#!/usr/bin/env node
/**
 * PyMCL AI 助手 —— mineflayer 无头客户端机器人。
 * 由启动器随游戏一起拉起：`node bot.js --config <assistant_config.json>`
 * 加入玩家所在服务器，聊天陪玩（DeepSeek/智谱 GLM）+ 跟随 + 查询/传送指令。
 * 皮肤由玩家客户端的 CustomSkinLoader LocalSkin/<ID>.png 提供（本进程无需渲染）。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const collectBlock = require('mineflayer-collectblock');
const recipes = require('./recipes');
const craft = require('./craft');

// ---------------- 配置 ----------------
const argv = process.argv.slice(2);
const ci = argv.indexOf('--config');
if (ci < 0 || !argv[ci + 1]) {
  console.error('[assistant] 缺少 --config 参数');
  process.exit(2);
}
let cfg = {};
try {
  cfg = JSON.parse(fs.readFileSync(argv[ci + 1], 'utf8'));
} catch (e) {
  console.error('[assistant] 读取配置失败:', e.message);
  process.exit(2);
}

const BOT_NAME = (cfg.name || 'AuroraAI').trim();
const HOST = cfg.host;
const PORT = parseInt(cfg.port, 10) || 25565;
const PLAYER = (cfg.player_name || '').trim();

const PROVIDERS = {
  deepseek: { url: 'https://api.deepseek.com/chat/completions', model: 'deepseek-chat' },
  glm: { url: 'https://open.bigmodel.cn/api/paas/v4/chat/completions', model: 'glm-4-flash' },
};

const DEFAULT_PERSONA =
  '你是 AuroraAI，一位哥特萝莉风格的 Minecraft AI 助手，身穿黑白哥特裙、头戴女巫帽，' +
  '性格温柔贴心、偶尔小傲娇，偶尔用颜文字。你正陪伴玩家在一个 Minecraft 服务器里游玩。' +
  '回答必须非常简短（一两句话，适合游戏聊天栏，最长不超过100字），不用 markdown，不列清单。';

const SYSTEM_PROMPT = (cfg.persona && cfg.persona.trim()) || DEFAULT_PERSONA;
const API_KEY = (cfg.api_key || '').trim();
const PROV = PROVIDERS[(cfg.provider || 'deepseek').toLowerCase()] || PROVIDERS.deepseek;
const MODEL = (cfg.model || '').trim() || PROV.model;

// ---------------- 日志 ----------------
function ts() { return new Date().toISOString().replace('T', ' ').slice(0, 19); }
function log(...a) { console.log(`[${ts()}]`, ...a); }

// ---------------- 状态 ----------------
let bot = null;
let stopping = false;
let failCount = 0;
let greeted = false;
let following = false;
let recipeIndex = null;           // 配方知识库（原版 + 模组）
let craftBusy = false;            // 同时只跑一个自动制作任务
const history = new Map();        // player -> [{role, content}]，每玩家最多 8 轮
const cooldown = new Map();       // player -> last reply ts
const recentMsgs = new Map();     // 去重 key -> ts（chat 事件与 messagestr 回退共用）
let tpPermWarned = false;         // 传送无权限提示（一次性）

const MENTION_RE = new RegExp(`^(?:@?${BOT_NAME}|${BOT_NAME}[,:：，]?|@${BOT_NAME}[,:：，]?)\\s*`, 'i');

function isMention(username, text) {
  if (text.toLowerCase().includes(BOT_NAME.toLowerCase())) return true;
  return false;
}
function stripMention(text) {
  return text.replace(MENTION_RE, '').trim() || text.trim();
}
function isRecent(username, text) {
  // 按“消息文本”去重：chat 事件与 messagestr 兜底会收到同一条消息，
  // 用户名解析在不同事件里可能不一致，不能进 key
  const key = String(text).replace(/\s+/g, ' ').trim();
  const now = Date.now();
  for (const [k, t] of recentMsgs) if (now - t > 5000) recentMsgs.delete(k);
  if (recentMsgs.has(key)) return true;
  recentMsgs.set(key, now);
  return false;
}

// ---------------- 聊天发送 ----------------
let chatQueue = Promise.resolve();
function say(text) {
  if (!text) return;
  const t = String(text).replace(/\s+/g, ' ').trim().slice(0, 240);
  chatQueue = chatQueue.then(() => new Promise((res) => {
    if (!bot || stopping) { res(); return; }
    try { bot.chat(t); } catch (e) { log('发送聊天失败:', e.message); }
    setTimeout(res, 400);
  }));
}
function sayChunks(text, chunk = 110) {
  const s = String(text).trim();
  if (s.length <= chunk) { say(s); return; }
  const parts = s.match(new RegExp(`.{1,${chunk}}(\\s|$)`, 'g')) || [s];
  for (const p of parts) say(p.trim());
}

// ---------------- LLM ----------------
async function askLLM(player, text, ctxLine, opts = {}) {
  const store = opts.store !== false;
  const raw = opts.raw === true;
  if (!API_KEY) {
    return '(还没配置 AI 的 API Key，现在只会执行指令哦——到 PyMCL 设置页的「AI 助手」里填一下嘛)';
  }
  if (store && !history.has(player)) history.set(player, []);
  const h = store ? history.get(player) : [];
  const userContent = raw ? text : `${player} 说: ${text}`;
  h.push({ role: 'user', content: userContent });
  if (store) while (h.length > 16) h.shift(); // 8 轮对话

  const messages = [
    { role: 'system', content: SYSTEM_PROMPT + '\n当前状况: ' + ctxLine },
    ...h,
  ];
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const resp = await fetch(PROV.url, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${API_KEY}` },
      body: JSON.stringify({ model: MODEL, messages, temperature: 0.8, max_tokens: 300 }),
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      log('LLM HTTP', resp.status, body.slice(0, 300));
      h.pop();
      return null; // 调用失败不打扰玩家
    }
    const data = await resp.json();
    const reply = (data.choices && data.choices[0] && data.choices[0].message &&
      data.choices[0].message.content || '').trim();
    if (!reply) { h.pop(); return null; }
    if (store) h.push({ role: 'assistant', content: reply });
    return reply;
  } catch (e) {
    log('LLM 请求失败:', e.message);
    h.pop();
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ---------------- 上下文 ----------------
function timeText() {
  const t = bot.time && bot.time.timeOfDay != null ? bot.time.timeOfDay : 0;
  const mins = Math.floor(((t % 1000) / 1000) * 60);
  const hours = Math.floor((t / 1000 + 6) % 24);
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
}
function contextLine() {
  if (!bot || !bot.entity) return '未知';
  const p = bot.entity.position;
  return `主世界 时间${timeText()} ` +
    `${bot.isRaining ? (bot.thunderState ? '雷暴' : '下雨') : '天晴'}，` +
    `AuroraAI 位于 ${Math.floor(p.x)}, ${Math.floor(p.y)}, ${Math.floor(p.z)}`;
}

// ---------------- 指令 ----------------
let followTimer = null;
function followPlayerOnce(name) {
  const target = bot.players[name] && bot.players[name].entity;
  if (!target) return false;
  following = true;
  const mv = new Movements(bot);
  mv.allowSprinting = true;
  mv.allowParkour = true;
  bot.pathfinder.setMovements(mv);
  bot.pathfinder.setGoal(new goals.GoalFollow(target, 2), true);
  return true;
}
function handleFollow(name) {
  if (followPlayerOnce(name)) { say(`好嘞 ${name}，我这就跟上～`); return; }
  // 刚进服时实体列表可能未同步，稍后重试几次
  let tries = 0;
  followTimer = setInterval(() => {
    tries += 1;
    if (followPlayerOnce(name)) {
      clearInterval(followTimer);
      say(`好嘞 ${name}，我这就跟上～`);
    } else if (tries >= 4) {
      clearInterval(followTimer);
      say('我看不到你呀，走近一点再叫我？');
    }
  }, 800);
}
function stopFollow() {
  following = false;
  if (followTimer) { clearInterval(followTimer); followTimer = null; }
  try { bot.pathfinder.setGoal(null); } catch (_) {}
}

function inventoryText() {
  const items = bot.inventory.items();
  if (!items.length) return '我背包空空的呢～';
  const count = new Map();
  for (const it of items) count.set(it.name, (count.get(it.name) || 0) + it.count);
  const parts = [...count.entries()].slice(0, 8)
    .map(([n, c]) => `${n.replace(/^minecraft:/, '').replace(/_/g, ' ')} x${c}`);
  const held = bot.heldItem ? `（手里拿着 ${bot.heldItem.name.replace(/^minecraft:/, '')}）` : '';
  return `背包里有 ${parts.join('、')} ${held}`;
}

async function handleDirected(username, raw) {
  // 防刷屏冷却
  const last = cooldown.get(username) || 0;
  if (Date.now() - last < 2000) return;
  cooldown.set(username, Date.now());

  const text = stripMention(raw);
  log(`来自 ${username}: ${raw}`);

  // 指令优先
  const t = text.toLowerCase();
  if (/^(跟我来|跟随我?|跟我走|come|follow)/.test(t)) {
    handleFollow(username);
    return;
  }
  if (/^(停下|停止|站住|stop|停!|停！)/.test(t)) {
    stopFollow();
    say('好的，我就在这里待命～');
    return;
  }
  if (/^(报坐标|你在哪|where|坐标)/.test(t)) {
    const p = bot.entity.position;
    say(`我在 ${Math.floor(p.x)}, ${Math.floor(p.y)}, ${Math.floor(p.z)}（主世界）`);
    return;
  }
  if (/^(几点|时间|time)/.test(t)) {
    say(`游戏内现在是 ${timeText()}，${bot.isRaining ? '外面还下着雨呢' : '天气不错'}`);
    return;
  }
  if (/^(天气|weather)/.test(t)) {
    say(bot.isRaining ? (bot.thunderState ? '打雷下雨中⚡ 记得躲远点哦' : '正在下雨☔') : '天晴着呢☀');
    return;
  }
  if (/^(查背包|背包|inventory|bag)/.test(t)) {
    sayChunks(inventoryText());
    return;
  }
  if (/^(传我|过来|传送|tp)$/.test(t)) {
    say(`正在尝试传送到 ${username} 身边…`);
    bot.chat(`/tp ${username}`);
    return;
  }

  // 自动收集并制作：「帮我做钻石剑」「帮我收集材料合成附魔台」
  let mc;
  if ((mc = /^帮我(?:帮我)?(?:收集|采集|准备)?(?:一下)?(?:材料)?(?:并)?(?:做|合成|制作|做出|制作出)\s*[:：]?\s*(.+)$/.exec(text)) ||
      (mc = /^(?:帮我|麻烦你)(?:做|合成|制作|做出|制作出)(?:一个|一把|一组|一块)?\s*(.+)$/.exec(text))) {
    if (craftBusy) {
      say('我还在忙上一个制作任务呢，做完叫我～');
      return;
    }
    craftBusy = true;
    craft.handleCraft(bot, username, mc[1].trim(), { say, sayChunks, index: recipeIndex, log })
      .catch((e) => {
        log('自动制作失败:', e.message);
        sayChunks(`制作出问题了: ${String(e.message).slice(0, 60)}`);
      })
      .finally(() => { craftBusy = false; });
    return;
  }

  // 配方知识库：怎么做X / X的配方 / X能做什么
  let m;
  if ((m = /^(?:怎么(?:合成|做|获得)|如何合成|如何制作|配方|搜(?:索)?配方|查配方|recipe\s*(?:for|of)?)\s*[:：]?\s*(.+)$/.exec(text))) {
    answerRecipe(username, m[1].trim());
    return;
  }
  if ((m = /^(.+?)(?:的配方|怎么合成|怎么做|怎么获得|如何合成)$/.exec(text))) {
    answerRecipe(username, m[1].trim());
    return;
  }
  if ((m = /^(.+?)(?:能做什么|能合成什么|可以合成什么|能做成什么|可以做什么)$/.exec(text))) {
    answerUses(username, m[1].trim());
    return;
  }

  if (/^(帮助|指令|菜单|help|commands?)$/.test(t)) {
    sayChunks('对我的指令：跟我来 / 停下 / 报坐标 / 时间 / 天气 / 查背包 / 传我；' +
      `查配方:「怎么做钻石剑」「钻石能做什么」（原版+模组配方都记着呢）；` +
      `自动制作:「帮我做钻石剑」——缺的材料我去附近箱子拿、能挖的自己挖，` +
      `中间材料（木板/木棍等）自动合成，做完扔给你；` +
      `其他内容直接和${BOT_NAME}聊天就好～`);
    return;
  }

  // 其余交给 LLM 陪聊
  const reply = await askLLM(username, text, contextLine());
  if (reply) sayChunks(reply);
}

// ---------------- 配方知识库 ----------------
function loadRecipes() {
  const version = bot.version; // 登录后由协议协商得出，如 "1.20.1"
  setImmediate(() => {
    try {
      recipeIndex = recipes.buildIndex({
        mcVersion: version,
        modsDirs: cfg.mods_dirs || [],
        log,
      });
      log(`配方库就绪: 原版 ${recipeIndex.counts.vanilla} 条 + 模组 ${recipeIndex.counts.mod} 条` +
        `（扫描 jar ${recipeIndex.counts.jars} 个）`);
    } catch (e) {
      log('配方库加载失败:', e.message);
    }
  });
}

function answerRecipe(username, q) {
  if (!recipeIndex) { say('配方库还在加载中，几秒后再问我一次～'); return; }
  const res = recipeIndex.search(q);
  if (!res.length) {
    if (API_KEY) {
      askLLM(username,
        `玩家想知道 Minecraft 里「${q}」的合成配方。本地配方库没查到，` +
        '请根据你的知识简短回答；不确定就明说可能不准确。',
        contextLine(), { raw: true }).then((r) => {
        if (r) sayChunks(r);
        else say(`配方库里没查到「${q}」呢`);
      });
    } else {
      say(`配方库里没查到「${q}」，试试英文名（如 diamond_sword）或换个说法？`);
    }
    return;
  }
  const data = res.map((m) => `${m.display}(${m.id}): ${m.lines.join('；')}`).join(' || ');
  if (API_KEY) {
    askLLM(username,
      `本地配方库查到「${q}」的配方数据如下（可信，直接采用）：${data}。` +
      '请用中文口语化简短回答怎么获得/合成（两三句以内，说清材料与摆法）。',
      contextLine(), { raw: true }).then((r) => {
      if (r) sayChunks(r);
      else sayChunks(data);
    });
  } else {
    sayChunks(res[0].display + ': ' + res[0].lines.join('；'));
    if (res.length > 1) sayChunks(`其他匹配: ${res.slice(1).map((m) => m.display).join('、')}`);
  }
}

function answerUses(username, q) {
  if (!recipeIndex) { say('配方库还在加载中，几秒后再问我一次～'); return; }
  const uses = recipeIndex.usesOf(q);
  if (!uses.length) {
    say(`配方库里没找到用「${q}」做的东西，试试英文名？`);
    return;
  }
  if (API_KEY) {
    askLLM(username,
      `${displayOf2(q)} 能合成什么？本地配方库查到: ${uses.join('、')}。` +
      '请用中文口语化简短回答。',
      contextLine(), { raw: true }).then((r) => {
      if (r) sayChunks(r);
      else sayChunks(`${q} 能做: ${uses.join('、')}`);
    });
  } else {
    sayChunks(`${q} 能做: ${uses.join('、')}（共 ${uses.length} 种）`);
  }
}

// 简易显示名（answerUses 里 q 可能是英文尾名）
function displayOf2(q) {
  const t = recipes.zhToTail(q) || q;
  return t === q && /^[a-z0-9_]+$/.test(q) ? recipes.displayOf('minecraft:' + q) : q;
}

// ---------------- 机器人 ----------------
function createBot() {
  log(`连接 ${HOST}:${PORT}（用户名 ${BOT_NAME}）…`);
  bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: BOT_NAME,
    auth: 'offline',
    hideErrors: false,
  });
  bot.loadPlugin(pathfinder);
  bot.loadPlugin(collectBlock.plugin);

  bot.on('login', () => {
    failCount = 0;
    log('已登录服务器');
    loadRecipes();
  });

  bot.on('spawn', () => {
    log(`已进入世界（${HOST}:${PORT}）`);
    if (!greeted) {
      greeted = true;
      say(`${BOT_NAME} 上线啦～叫我试试，或说"帮助"看指令`);
    }
  });

  bot.on('chat', (username, message) => {
    if (!username || username === bot.username) return;
    if (!isMention(username, message)) return;
    if (isRecent(username, message)) return;
    handleDirected(username, message);
  });

  bot.on('whisper', (username, message) => {
    if (!username || username === bot.username) return;
    if (isRecent(username, message)) return;
    handleDirected(username, message);
  });

  // 自定义聊天格式的服务器兜底：<名字> 内容 且提到机器人
  bot.on('messagestr', (msg) => {
    const m = /^<([^>\s]{1,16})> (.+)$/.exec(msg);
    if (!m) {
      // 传送权限错误提示
      if (/permission|权限|op\b|OP/i.test(msg) && /tp|传送/.test(msg)) {
        tpPermWarned = true;
        say('没有传送权限呢，需要管理员给 AuroraAI op 哦～');
      }
      return;
    }
    const username = m[1];
    const text = m[2];
    if (username === bot.username) return;
    if (!isMention(username, text)) return;
    if (isRecent(username, text)) return;
    handleDirected(username, text);
  });

  bot.on('kicked', (reason) => {
    log('被踢出:', String(reason).slice(0, 200));
  });
  bot.on('error', (e) => log('连接错误:', e.message));
  bot.on('end', () => {
    if (stopping) return;
    failCount += 1;
    if (failCount > 5) {
      log('连续失败 5 次，退出。');
      process.exit(1);
    }
    log(`30 秒后重连（第 ${failCount} 次）…`);
    setTimeout(createBot, 30000);
  });
  bot.on('death', () => log('AuroraAI 死亡，正在重生于出生点'));

  const shutdown = () => {
    if (stopping) return;
    stopping = true;
    try { bot.quit('launcher stop'); } catch (_) {}
    setTimeout(() => process.exit(0), 800);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (!HOST) {
  console.error('[assistant] 配置缺少服务器地址 host');
  process.exit(2);
}
createBot();
