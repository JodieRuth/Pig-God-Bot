import { createServer } from 'node:http';
import { mkdir, readFile, writeFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = join(__dirname, 'data');
const IMAGE_CACHE_DIR = join(__dirname, 'cache', 'images');
const DATA_FILE = join(DATA_DIR, 'vndb-data.json');
const GZIP_FILE = join(DATA_DIR, 'vndb-data.json.gz');
const MANIFEST_FILE = join(DATA_DIR, 'manifest.json');
const REMOTE_MANIFEST_URL = process.env.VNDB_PROFILE_MANIFEST_URL || 'https://raw.githubusercontent.com/JodieRuth/VNDB-Profile-Search/data-latest/public/data/manifest.json';
const GITHUB_MIRROR_PREFIXES = (process.env.GITHUB_MIRROR_PREFIXES || 'https://gh.llkk.cc/,https://ghproxy.net/,https://gh-proxy.com/').split(',').map((item) => item.trim()).filter(Boolean);
const VNDB_API_BASE = process.env.VNDB_API_BASE || 'https://api.vndb.org/kana';
const PORT = Number(process.env.PORT || process.env.VNDB_JSON_SERVER_PORT || 8787);
const UPDATE_INTERVAL_MS = 60 * 60 * 1000;

let data = null;
let manifest = null;
let loadingPromise = null;
let lastUpdateCheck = null;
let lastDataLoad = null;
let tagMeta = new Map();
let traitMeta = new Map();
let vnById = new Map();
let characterById = new Map();
let tagSearchIndexSpoilerOff = null;
let tagSearchIndexSpoilerOn = null;
let traitSearchIndexSpoilerOff = null;
let traitSearchIndexSpoilerOn = null;

const normalizeTitle = (value) => String(value ?? '').toLocaleLowerCase().replace(/[\s\-_~:：!！?？()[\]（）【】「」『』,，.。]/g, '');
const text = (value) => String(value ?? '').trim().toLocaleLowerCase();
const isVnId = (value) => /^v\d+$/i.test(String(value ?? '').trim());
const isCharId = (value) => /^c\d+$/i.test(String(value ?? '').trim());
const idOf = (value) => Number(String(value ?? '').trim().slice(1));
const asArray = (value) => Array.isArray(value) ? value : value == null ? [] : [value];
const uniqueNumbers = (value) => [...new Set(asArray(value).map((item) => Number(String(item).replace(/^[vc]/i, ''))).filter(Number.isFinite))];
const defaultRoleFilter = () => ({ primary: true, main: true, side: true, appears: false });

function jsonResponse(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-allow-headers': 'content-type' });
  response.end(body);
}

function readRequestJson(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8').trim();
      if (!body) resolve({});
      else {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(new Error(`Invalid JSON: ${error.message}`));
        }
      }
    });
    request.on('error', reject);
  });
}

async function withRetries(label, task, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await task();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, attempt * 3000));
    }
  }
  throw new Error(`${label} failed after ${attempts} attempts: ${lastError?.message || lastError}`);
}

function githubMirrorUrl(url, prefix) {
  if (!/^https?:\/\//i.test(url)) return url;
  if (!/(^https?:\/\/raw\.githubusercontent\.com\/|^https?:\/\/github\.com\/)/i.test(url)) return url;
  return prefix + url;
}

function fetchPlan(url) {
  const plan = [{ label: 'system proxy', url, proxy: true }];
  for (const prefix of GITHUB_MIRROR_PREFIXES) plan.push({ label: `mirror ${prefix.replace(/\/$/, '')}`, url: githubMirrorUrl(url, prefix), proxy: false });
  plan.push({ label: 'direct', url, proxy: false });
  return plan;
}

function proxyEnv() {
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy || '';
  if (!proxy) return null;
  const env = { ...process.env };
  env.HTTPS_PROXY = proxy;
  env.HTTP_PROXY = proxy;
  env.https_proxy = proxy;
  env.http_proxy = proxy;
  return env;
}

function systemProxyUnavailableError() {
  return new Error('system proxy unavailable: HTTPS_PROXY/HTTP_PROXY is not configured');
}

function fetchByCurl(url, options, timeoutMs) {
  const env = proxyEnv();
  if (!env) return Promise.reject(systemProxyUnavailableError());
  return new Promise((resolve, reject) => {
    const args = ['-L', '--fail', '--silent', '--show-error', '--max-time', String(Math.ceil(timeoutMs / 1000))];
    if (options?.method === 'POST') args.push('-X', 'POST');
    for (const [key, value] of Object.entries(options?.headers ?? {})) args.push('-H', `${key}: ${value}`);
    if (options?.body != null) args.push('--data-binary', String(options.body));
    args.push(url);
    const child = spawn('curl', args, { env, windowsHide: true });
    const chunks = [];
    const errors = [];
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`curl timeout after ${timeoutMs}ms`));
    }, timeoutMs + 1000);
    child.stdout.on('data', (chunk) => chunks.push(chunk));
    child.stderr.on('data', (chunk) => errors.push(chunk));
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code === 0) resolve(Buffer.concat(chunks));
      else reject(new Error(`curl exit ${code}: ${Buffer.concat(errors).toString('utf8').trim()}`));
    });
  });
}

async function fetchBuffer(url, options = {}, timeoutMs = 60000, useSystemProxy = false) {
  if (useSystemProxy) return fetchByCurl(url, options, timeoutMs);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal, ...options });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return Buffer.from(await response.arrayBuffer());
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchWithFallback(label, url, options = {}, timeoutMs = 60000) {
  const failures = [];
  for (const item of fetchPlan(url)) {
    try {
      const buffer = await withRetries(`${label} ${item.label} ${item.url}`, () => fetchBuffer(item.url, options, timeoutMs, item.proxy));
      if (item.url !== url || item.proxy) console.error(new Date().toISOString(), `${label} downloaded via ${item.label}`);
      return buffer;
    } catch (error) {
      failures.push(`${item.label}: ${String(error?.message || error)}`);
    }
  }
  throw new Error(`${label} failed: ${failures.join(' | ')}`);
}

async function fetchJson(url) {
  const buffer = await fetchWithFallback(`Fetch JSON ${url}`, url, {}, 60000);
  return JSON.parse(buffer.toString('utf8'));
}

async function fetchBytes(url, options = {}) {
  return fetchWithFallback(`Fetch bytes ${url}`, url, options, 300000);
}

async function postJson(url, payload) {
  return withRetries(`POST JSON ${url}`, async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      const textValue = await response.text();
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${textValue}`);
      return textValue ? JSON.parse(textValue) : null;
    } finally {
      clearTimeout(timeout);
    }
  });
}

function resolveDataUrl(remoteManifest) {
  const path = remoteManifest.dataPath ?? remoteManifest.path;
  if (!path) throw new Error('Manifest missing dataPath/path');
  if (/^https?:\/\//i.test(path)) return path;
  return new URL(path, REMOTE_MANIFEST_URL).toString();
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function decode(value) {
  try {
    return Buffer.from(String(value), 'base64').toString('utf8');
  } catch {
    return value;
  }
}

function decodeIfNeeded(value, encoded) {
  return value && encoded ? decode(value) : value ?? null;
}

function decodeLocalData(raw) {
  const decodeProducer = (producer) => ({
    ...producer,
    name: decodeIfNeeded(producer.name, producer.nameEncoded) ?? producer.name,
    original: decodeIfNeeded(producer.original, producer.originalEncoded)
  });
  const vns = raw.vns.map((vn) => ({
    ...vn,
    title: decodeIfNeeded(vn.title, vn.titleEncoded) ?? vn.title,
    original: decodeIfNeeded(vn.original, vn.originalEncoded),
    aliases: decodeIfNeeded(vn.aliases, vn.aliasesEncoded) ?? '',
    developers: vn.developers.map(decodeProducer),
    publishers: vn.publishers.map(decodeProducer),
    search: decodeIfNeeded(vn.search, vn.searchEncoded) ?? vn.search
  }));
  const characters = raw.characters.map((character) => ({
    ...character,
    name: decodeIfNeeded(character.name, character.nameEncoded) ?? character.name,
    original: decodeIfNeeded(character.original, character.originalEncoded),
    search: decodeIfNeeded(character.search, character.searchEncoded) ?? character.search,
    aliases: character.aliasesEncoded ? character.aliases.map((alias) => decode(alias)) : character.aliases
  }));
  const decodeMeta = (metaItem) => ({
    ...metaItem,
    name: decodeIfNeeded(metaItem.name, metaItem.nameEncoded) ?? metaItem.name,
    nameEncoded: false,
    nameZh: decodeIfNeeded(metaItem.nameZh, metaItem.nameZhEncoded) ?? undefined,
    nameZhEncoded: false,
    nameJa: decodeIfNeeded(metaItem.nameJa, metaItem.nameJaEncoded) ?? undefined,
    nameJaEncoded: false,
    alias: decodeIfNeeded(metaItem.alias, metaItem.aliasEncoded ?? metaItem.nameEncoded) ?? '',
    aliasEncoded: false,
    description: decodeIfNeeded(metaItem.description, metaItem.descriptionEncoded) ?? undefined,
    descriptionEncoded: false,
    descriptionZh: decodeIfNeeded(metaItem.descriptionZh, metaItem.descriptionZhEncoded) ?? undefined,
    descriptionZhEncoded: false,
    descriptionJa: decodeIfNeeded(metaItem.descriptionJa, metaItem.descriptionJaEncoded) ?? undefined,
    descriptionJaEncoded: false
  });
  return { ...raw, vns, characters, tags: raw.tags.map(decodeMeta), traits: raw.traits.map(decodeMeta) };
}

async function readLocalManifest() {
  if (!existsSync(MANIFEST_FILE)) return null;
  return JSON.parse(await readFile(MANIFEST_FILE, 'utf8'));
}

async function downloadLatestData(force = false) {
  await mkdir(DATA_DIR, { recursive: true });
  const remote = await fetchJson(REMOTE_MANIFEST_URL);
  const local = await readLocalManifest();
  lastUpdateCheck = new Date().toISOString();
  if (!force && local?.sha256 && remote?.sha256 && local.sha256 === remote.sha256 && existsSync(DATA_FILE)) {
    manifest = local;
    return { updated: false, manifest: local };
  }
  const bytes = await fetchBytes(resolveDataUrl(remote));
  if (remote.sha256) {
    const actual = sha256(bytes);
    if (actual !== remote.sha256) throw new Error(`Downloaded data sha256 mismatch: ${actual} !== ${remote.sha256}`);
  }
  const textValue = bytes[0] === 0x1f && bytes[1] === 0x8b ? gunzipSync(bytes).toString('utf8') : bytes.toString('utf8');
  await writeFile(GZIP_FILE, bytes);
  await writeFile(DATA_FILE, textValue, 'utf8');
  await writeFile(MANIFEST_FILE, JSON.stringify(remote, null, 2), 'utf8');
  manifest = remote;
  return { updated: true, manifest: remote };
}

function commonPrefixLength(a, b) {
  const left = normalizeTitle(a);
  const right = normalizeTitle(b);
  let count = 0;
  while (count < left.length && count < right.length && left[count] === right[count]) count += 1;
  return count;
}

function producerIds(vn) {
  return new Set([...(vn.developers ?? []), ...(vn.publishers ?? [])].map((producer) => producer.id));
}

function characterDeveloperIds(character) {
  const ids = new Set();
  for (const [vnId] of character.vns) {
    const vn = vnById.get(vnId);
    if (!vn) continue;
    for (const developer of vn.developers) ids.add(developer.id);
  }
  return ids;
}

function selectedCharacterDeveloperIds(characterIds) {
  const ids = new Set();
  for (const id of characterIds) {
    const character = characterById.get(id);
    if (!character) continue;
    for (const developerId of characterDeveloperIds(character)) ids.add(developerId);
  }
  return ids;
}

function characterCompanyBoost(character, referenceDeveloperIds) {
  if (!referenceDeveloperIds.size) return 1;
  for (const [vnId] of character.vns) {
    const vn = vnById.get(vnId);
    if (vn?.developers?.some((developer) => referenceDeveloperIds.has(developer.id))) return 1.33;
  }
  return 1;
}

function isSameCompanyPrefixDuplicate(candidate, samples) {
  const candidateProducers = producerIds(candidate);
  if (!candidateProducers.size) return false;
  return samples.some((sample) => [...producerIds(sample)].some((id) => candidateProducers.has(id)) && commonPrefixLength(candidate.title, sample.title) > 3);
}

function itemSpoiler(item, kind) {
  return kind === 'tag' ? item[2] ?? 0 : item[1] ?? 0;
}

function itemLie(item, kind) {
  if (kind !== 'tag') return item[2] ?? 0;
  const lieCount = item[3] ?? 0;
  const voteCount = item[4];
  if (voteCount === undefined) return lieCount;
  return voteCount > 50 ? lieCount / voteCount >= 0.05 : lieCount >= 4;
}

function metaAllowedByFilters(metaItem, kind, includeSexual, includeSpoiler, includeBlocked = true, includeTechnical = true) {
  if (!metaItem) return false;
  if (metaItem.sexual && !includeSexual) return false;
  if (!includeSpoiler && (metaItem.defaultspoil ?? 0) > 0) return false;
  if (kind === 'tag' && metaItem.blocked && !includeBlocked) return false;
  if (kind === 'tag' && metaItem.tech && !includeTechnical) return false;
  return true;
}

function canUseMetaForSearch(metaItem, spoiler, includeSpoiler, allowedSexualIds) {
  if (metaItem.sexual && !allowedSexualIds?.has(metaItem.id)) return false;
  if (!includeSpoiler && Math.max(spoiler, metaItem.defaultspoil ?? 0) > 0) return false;
  return true;
}

function makeVector(items, meta, kind, includeSpoiler, includeParents = false, allowedSexualIds, capParentWeight = false) {
  const vector = new Map();
  for (const item of items ?? []) {
    const id = item[0];
    const metaItem = meta.get(id);
    const spoiler = itemSpoiler(item, kind);
    const lie = itemLie(item, kind);
    if (!metaItem || lie) continue;
    if (!canUseMetaForSearch(metaItem, spoiler, includeSpoiler, allowedSexualIds)) continue;
    const weight = kind === 'tag' ? item[1] ?? 1 : 1;
    vector.set(id, Math.max(vector.get(id) ?? 0, weight));
    if (includeParents) {
      for (const parentId of metaItem.parents ?? []) {
        const parent = meta.get(parentId);
        if (!parent || !canUseMetaForSearch(parent, 0, includeSpoiler, allowedSexualIds)) continue;
        const parentWeight = capParentWeight ? Math.min(weight * 0.55, 0.55) : weight * 0.55;
        vector.set(parentId, Math.max(vector.get(parentId) ?? 0, parentWeight));
      }
    }
  }
  return vector;
}

function addPosting(postings, metaId, index) {
  const list = postings.get(metaId) ?? [];
  list.push(index);
  postings.set(metaId, list);
}

function buildTagSearchIndex(includeSpoiler) {
  const vectors = [];
  const postings = new Map();
  const sexualIds = new Set([...tagMeta.values()].filter((item) => item.sexual).map((item) => item.id));
  for (let index = 0; index < data.vns.length; index += 1) {
    const vn = data.vns[index];
    const vector = makeVector(vn.tags, tagMeta, 'tag', includeSpoiler, true, sexualIds, true);
    vectors[index] = vector;
    for (const id of vector.keys()) addPosting(postings, id, index);
  }
  return { vectors, postings };
}

function buildTraitSearchIndex(includeSpoiler) {
  const vectors = [];
  const postings = new Map();
  const sexualIds = new Set([...traitMeta.values()].filter((item) => item.sexual).map((item) => item.id));
  for (let index = 0; index < data.characters.length; index += 1) {
    const character = data.characters[index];
    const vector = makeVector(character.traits, traitMeta, 'trait', includeSpoiler, true, sexualIds);
    vectors[index] = vector;
    for (const id of vector.keys()) addPosting(postings, id, index);
  }
  return { vectors, postings };
}

function metaIsAutoIgnored(metaItem) {
  return Boolean(metaItem?.tech || metaItem?.blocked);
}

function omitUnprioritizedSpecialTags(vector, meta, priorityIds) {
  const result = new Map();
  for (const [id, value] of vector) if (!metaIsAutoIgnored(meta.get(id)) || priorityIds.has(id)) result.set(id, value);
  return result;
}

function mergeVectors(vectors) {
  const merged = new Map();
  for (const vector of vectors) for (const [id, value] of vector) merged.set(id, (merged.get(id) ?? 0) + value);
  return merged;
}

function expandVectorParents(vector, meta, allowedSexualIds) {
  const result = new Map(vector);
  for (const [id, value] of vector) {
    const metaItem = meta.get(id);
    if (!metaItem) continue;
    for (const parentId of metaItem.parents ?? []) {
      const parent = meta.get(parentId);
      if (!parent || !canUseMetaForSearch(parent, 0, true, allowedSexualIds)) continue;
      result.set(parentId, Math.max(result.get(parentId) ?? 0, value * 0.55));
    }
  }
  return result;
}

function hashText(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function stableUnitRandom(seed, key) {
  return (hashText(`${seed}|${key}`) + 1) / 4294967297;
}

function sampledSearchVector(vector, limit, meta, priorityIds, round, allowedSexualIds, coverageCounts = new Map()) {
  const expanded = expandVectorParents(vector, meta, allowedSexualIds);
  const count = Math.max(1, limit);
  const entries = [...expanded.entries()].sort((a, b) => b[1] - a[1]);
  const candidates = entries.filter(([id]) => !priorityIds.has(id) && !metaIsAutoIgnored(meta.get(id)) && !meta.get(id)?.sexual);
  const seed = entries.map(([id, value]) => `${id}:${value}`).join('|');
  const selected = new Set();
  const pool = [...candidates];
  while (selected.size < count && pool.length) {
    let bestIndex = 0;
    let bestScore = Number.POSITIVE_INFINITY;
    for (let index = 0; index < pool.length; index += 1) {
      const [id, value] = pool[index];
      const seenCount = coverageCounts.get(id) ?? 0;
      const coverageBoost = seenCount === 0 ? 1.8 : 1;
      const repeatPenalty = Math.pow(1 + seenCount, 0.75);
      const weight = Math.max(value * coverageBoost / repeatPenalty, 0.000001);
      const random = Math.max(stableUnitRandom(seed, `${round}|${selected.size}|${id}`), 0.000001);
      const score = -Math.log(random) / weight;
      if (score < bestScore) {
        bestScore = score;
        bestIndex = index;
      }
    }
    selected.add(pool[bestIndex][0]);
    pool.splice(bestIndex, 1);
  }
  if (round <= 0 || candidates.length <= count) for (const [id] of candidates.slice(0, count)) selected.add(id);
  const result = new Map();
  for (const [id, value] of entries) if (selected.has(id)) result.set(id, value);
  const topWeight = entries.reduce((max, [, value]) => Math.max(max, value), 1);
  for (const id of priorityIds) if (expanded.has(id)) result.set(id, Math.max(expanded.get(id) ?? 0, topWeight * 2));
  return result;
}

function buildActiveVnProfile(selectedIds, selectedWeights, negativeIds, negativeWeights, includeSpoiler, priorityIds, negativePriorityIds, limit, round = 0, coverageCounts = new Map()) {
  const selected = selectedIds.map((id) => vnById.get(id)).filter(Boolean);
  if (!selected.length) return new Map();
  const positiveVectors = selected.map((vn, index) => {
    const vec = makeVector(vn.tags, tagMeta, 'tag', includeSpoiler, false, priorityIds);
    const weight = selectedWeights[index] ?? 1.0;
    if (weight === 1.0) return vec;
    return new Map([...vec.entries()].map(([id, value]) => [id, value * weight]));
  });
  const direct = mergeVectors(positiveVectors);
  const negative = negativeIds.map((id) => vnById.get(id)).filter(Boolean);
  if (negative.length) {
    const negativeVecs = negative.map((vn, index) => {
      const vec = makeVector(vn.tags, tagMeta, 'tag', includeSpoiler, false, negativePriorityIds);
      const weight = negativeWeights[index] ?? 1.0;
      return new Map([...vec.entries()].map(([id, value]) => [id, value * weight * 0.5]));
    });
    const negMerged = mergeVectors(negativeVecs);
    for (const [id, value] of negMerged) {
      const nextValue = (direct.get(id) ?? 0) - value;
      if (nextValue > 0) direct.set(id, nextValue);
      else direct.delete(id);
    }
  }
  for (const id of negativePriorityIds) direct.delete(id);
  return sampledSearchVector(omitUnprioritizedSpecialTags(direct, tagMeta, priorityIds), limit, tagMeta, priorityIds, round, priorityIds, coverageCounts);
}

function buildActiveCharacterProfile(selectedIds, selectedWeights, negativeIds, negativeWeights, includeSpoiler, priorityIds, negativePriorityIds, limit, round = 0, coverageCounts = new Map()) {
  const selected = selectedIds.map((id) => characterById.get(id)).filter(Boolean);
  if (!selected.length) return new Map();
  const positiveVectors = selected.map((character, index) => {
    const vec = makeVector(character.traits, traitMeta, 'trait', includeSpoiler, false, priorityIds);
    const weight = selectedWeights[index] ?? 1.0;
    if (weight === 1.0) return vec;
    return new Map([...vec.entries()].map(([id, value]) => [id, value * weight]));
  });
  const direct = mergeVectors(positiveVectors);
  const negative = negativeIds.map((id) => characterById.get(id)).filter(Boolean);
  if (negative.length) {
    const negativeVecs = negative.map((character, index) => {
      const vec = makeVector(character.traits, traitMeta, 'trait', includeSpoiler, false, negativePriorityIds);
      const weight = negativeWeights[index] ?? 1.0;
      return new Map([...vec.entries()].map(([id, value]) => [id, value * weight * 0.5]));
    });
    const negMerged = mergeVectors(negativeVecs);
    for (const [id, value] of negMerged) {
      const nextValue = (direct.get(id) ?? 0) - value;
      if (nextValue > 0) direct.set(id, nextValue);
      else direct.delete(id);
    }
  }
  for (const id of negativePriorityIds) direct.delete(id);
  return sampledSearchVector(direct, limit, traitMeta, priorityIds, round, priorityIds, coverageCounts);
}

function priorityMatch(query, candidate) {
  let matched = 0;
  for (const id of query) if (candidate.has(id)) matched += 1;
  return matched;
}

function cosine(a, b) {
  let dot = 0;
  let aa = 0;
  let bb = 0;
  for (const value of a.values()) aa += value * value;
  for (const value of b.values()) bb += value * value;
  for (const [id, value] of a) dot += value * (b.get(id) ?? 0);
  if (!aa || !bb) return 0;
  return dot / (Math.sqrt(aa) * Math.sqrt(bb));
}

function vectorScore(query, candidate) {
  let queryWeight = 0;
  let matchedWeight = 0;
  for (const [id, value] of query) {
    queryWeight += value;
    if (candidate.has(id)) matchedWeight += value;
  }
  const coverage = queryWeight ? matchedWeight / queryWeight : 0;
  return coverage * 0.7 + cosine(query, candidate) * 0.3;
}

function overlap(a, b) {
  let count = 0;
  for (const id of a.keys()) if (b.has(id)) count += 1;
  return count;
}

function groupedMetaConfidence(groups, candidate) {
  if (!groups.length) return 0;
  let confidence = 0;
  for (const group of groups) {
    let best = 0;
    for (const id of group.alternatives) best = Math.max(best, candidate.get(id) ?? 0);
    confidence += Math.min(best, 1);
  }
  return Math.min(confidence / groups.length, 1);
}

function groupedPriorityMatch(groups, candidate) {
  let matched = 0;
  for (const group of groups) if (groupedMetaConfidence([group], candidate) > 0) matched += 1;
  return matched;
}

function groupedMetaScore(groups, candidate) {
  if (!groups.length) return 0;
  let matched = 0;
  let strength = 0;
  for (const group of groups) {
    let best = 0;
    for (const id of group.alternatives) best = Math.max(best, candidate.get(id) ?? 0);
    if (best > 0) matched += 1;
    strength += Math.min(best / 3, 1);
  }
  return matched / groups.length * 0.82 + strength / groups.length * 0.18;
}

function roleAllowed(role, filter) {
  if (role === 'primary') return filter.primary;
  if (role === 'main') return filter.main;
  if (role === 'side') return filter.side;
  if (role === 'appears') return filter.appears;
  return filter.appears;
}

function characterHasQualifiedVn(character, minVotes, roleFilter) {
  return character.vns.some(([id, role]) => (vnById.get(id)?.votes ?? 0) >= minVotes && (!roleFilter || roleAllowed(role, roleFilter)));
}

function characterRoleFilteredVnIds(character, roleFilter) {
  return new Set(character.vns.filter(([, role]) => roleAllowed(role, roleFilter)).map(([id]) => id));
}

function characterAverageScore(character) {
  const scores = character.vns.map(([id]) => vnById.get(id)?.average ?? 0).filter((score) => score > 0);
  if (!scores.length) return 0;
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

function characterAverageForMatchedVns(character, matchedVnIds) {
  const scores = character.vns.filter(([id]) => matchedVnIds.has(id)).map(([id]) => vnById.get(id)?.average ?? 0).filter((score) => score > 0);
  if (!scores.length) return characterAverageScore(character);
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

function vnResultScore(vn) {
  return vn.similarity * 100 + vn.rating / 10 + Math.log10(vn.votes || 1);
}

function characterResultScore(character, preferAverage) {
  return (character.similarity * 100 + (preferAverage ? characterAverageScore(character) / 10 : character.score / 100) + (character.consensusBonus ?? 0) * 0.8) * (character.companyBoost ?? 1);
}

function itemTitle(item) {
  return ('title' in item ? item.original || item.title : item.original || item.name).toLocaleLowerCase();
}

function sortNumberByDirection(value, direction) {
  return direction === 'desc' ? -value : value;
}

function sortTextByDirection(left, right, direction) {
  return direction === 'desc' ? right.localeCompare(left) : left.localeCompare(right);
}

function similarityBucket(value) {
  if (value >= 0.75) return 5;
  if (value >= 0.6) return 4;
  if (value >= 0.45) return 3;
  if (value >= 0.3) return 2;
  if (value >= 0.15) return 1;
  return 0;
}

function compareSimilarityBucket(a, b) {
  return similarityBucket(b.similarity) - similarityBucket(a.similarity) || b.similarity - a.similarity;
}

function vnRatingSortScore(vn) {
  return vnResultScore(vn) + vn.rating / 20 + Math.log10(vn.votes || 1) / 5;
}

function vnVotesSortScore(vn) {
  return vnResultScore(vn) + Math.log10(vn.votes || 1) * 0.7 + vn.rating / 40;
}

function characterMaxVotes(character) {
  return Math.max(0, ...character.vns.map(([id]) => vnById.get(id)?.votes ?? 0));
}

function characterRatingSortScore(character, preferAverage) {
  return characterResultScore(character, preferAverage) + characterAverageScore(character) / 20 + Math.log10(characterMaxVotes(character) || 1) / 5;
}

function characterVotesSortScore(character, preferAverage) {
  return characterResultScore(character, preferAverage) + Math.log10(characterMaxVotes(character) || 1) * 0.7 + characterAverageScore(character) / 40;
}

function confidenceSortScore(item, baseScore) {
  if (!item.priorityTotal) return baseScore;
  return baseScore + item.priorityConfidence * 12 + item.priorityMatched * 2 + item.overlap * 0.1;
}

function mixedResultScore(result, preferAverage) {
  const vn = vnById.get(result.vnId);
  const character = characterById.get(result.characterId);
  if (!vn || !character) return result.similarity * 100;
  return result.similarity * 100 + vn.rating / 10 + (preferAverage ? characterAverageForMatchedVns(character, new Set([vn.id])) / 10 : character.score / 100);
}

function mixedConfidenceSortScore(result, baseScore) {
  if (!result.priorityTotal) return baseScore;
  return baseScore + result.priorityConfidence * 12 + result.priorityMatched * 2;
}

function sortVnRefs(items, sort, direction) {
  return [...items].sort((a, b) => {
    const leftVn = vnById.get(a.id);
    const rightVn = vnById.get(b.id);
    if (sort === 'title' && leftVn && rightVn) return compareSimilarityBucket(a, b) || sortTextByDirection(itemTitle(leftVn), itemTitle(rightVn), direction) || a.id - b.id;
    const left = sort === 'rating' ? vnRatingSortScore({ ...leftVn, ...a }) : sort === 'votes' ? vnVotesSortScore({ ...leftVn, ...a }) : sort === 'confidence' ? confidenceSortScore(a, vnResultScore({ ...leftVn, ...a })) : vnResultScore({ ...leftVn, ...a });
    const right = sort === 'rating' ? vnRatingSortScore({ ...rightVn, ...b }) : sort === 'votes' ? vnVotesSortScore({ ...rightVn, ...b }) : sort === 'confidence' ? confidenceSortScore(b, vnResultScore({ ...rightVn, ...b })) : vnResultScore({ ...rightVn, ...b });
    return sortNumberByDirection(left - right, direction) || a.id - b.id;
  });
}

function sortCharacterRefs(items, sort, direction, preferAverage) {
  return [...items].sort((a, b) => {
    if (sort === 'title') return compareSimilarityBucket(a, b) || sortTextByDirection(itemTitle(a.character), itemTitle(b.character), direction) || a.id - b.id;
    const left = sort === 'rating' ? characterRatingSortScore({ ...a.character, ...a }, preferAverage) : sort === 'votes' ? characterVotesSortScore({ ...a.character, ...a }, preferAverage) : sort === 'confidence' ? confidenceSortScore(a, characterResultScore({ ...a.character, ...a }, preferAverage)) : characterResultScore({ ...a.character, ...a }, preferAverage);
    const right = sort === 'rating' ? characterRatingSortScore({ ...b.character, ...b }, preferAverage) : sort === 'votes' ? characterVotesSortScore({ ...b.character, ...b }, preferAverage) : sort === 'confidence' ? confidenceSortScore(b, characterResultScore({ ...b.character, ...b }, preferAverage)) : characterResultScore({ ...b.character, ...b }, preferAverage);
    return sortNumberByDirection(left - right, direction) || a.id - b.id;
  });
}

function sortMixedRefs(items, sort, direction, preferAverage) {
  return [...items].sort((a, b) => {
    const leftVn = vnById.get(a.vnId);
    const rightVn = vnById.get(b.vnId);
    const leftCharacter = characterById.get(a.characterId);
    const rightCharacter = characterById.get(b.characterId);
    if (sort === 'title' && leftVn && rightVn && leftCharacter && rightCharacter) return compareSimilarityBucket(a, b) || sortTextByDirection(`${itemTitle(leftVn)} ${itemTitle(leftCharacter)}`, `${itemTitle(rightVn)} ${itemTitle(rightCharacter)}`, direction) || a.characterId - b.characterId;
    const leftBase = mixedResultScore(a, preferAverage);
    const rightBase = mixedResultScore(b, preferAverage);
    const left = sort === 'rating' ? leftBase + (leftVn?.rating ?? 0) / 20 + Math.log10(leftVn?.votes || 1) / 5 : sort === 'votes' ? leftBase + Math.log10(leftVn?.votes || 1) * 0.7 + (leftVn?.rating ?? 0) / 40 : sort === 'confidence' ? mixedConfidenceSortScore(a, leftBase) : leftBase;
    const right = sort === 'rating' ? rightBase + (rightVn?.rating ?? 0) / 20 + Math.log10(rightVn?.votes || 1) / 5 : sort === 'votes' ? rightBase + Math.log10(rightVn?.votes || 1) * 0.7 + (rightVn?.rating ?? 0) / 40 : sort === 'confidence' ? mixedConfidenceSortScore(b, rightBase) : rightBase;
    return sortNumberByDirection(left - right, direction) || a.characterId - b.characterId;
  });
}

function priorityBucketedResults(candidates, total, score) {
  const sorted = [...candidates].sort((a, b) => score(b) - score(a));
  if (!total) return sorted;
  const result = [];
  const minimumMatched = total >= 5 ? total - 2 : total >= 3 ? total - 1 : total;
  for (let matched = total; matched >= minimumMatched; matched -= 1) result.push(...sorted.filter((item) => item.priorityMatched === matched));
  return result;
}

function characterConsensusBonuses(candidates, sampleProfiles) {
  if (!sampleProfiles.length || !candidates.length) return new Map();
  const totals = new Map();
  for (const profile of sampleProfiles) {
    const ranked = candidates.map((candidate) => ({ id: candidate.id, score: vectorScore(profile, candidate.vector) })).filter((candidate) => candidate.score > 0).sort((a, b) => b.score - a.score || a.id - b.id);
    const denominator = Math.max(1, ranked.length);
    ranked.forEach((candidate, index) => totals.set(candidate.id, (totals.get(candidate.id) ?? 0) + (denominator - index) / denominator));
  }
  return new Map([...totals.entries()].map(([id, value]) => [id, value / sampleProfiles.length]));
}

function profileSignature(profile) {
  return [...profile.entries()].sort((a, b) => a[0] - b[0]).map(([id, value]) => `${id}:${value}`).join('|');
}

function buildDistinctProfiles(rounds, buildProfile) {
  const profiles = [];
  const signatures = new Map();
  const coverageCounts = new Map();
  let repeatedProfiles = 0;
  for (let round = 0; round < rounds; round += 1) {
    const profile = buildProfile(round, coverageCounts);
    if (!profile.size) break;
    const signature = profileSignature(profile);
    const signatureCount = signatures.get(signature) ?? 0;
    if (signatureCount > 0) {
      repeatedProfiles += 1;
      if (repeatedProfiles >= 10) break;
    }
    signatures.set(signature, signatureCount + 1);
    profiles.push(profile);
    for (const id of profile.keys()) coverageCounts.set(id, (coverageCounts.get(id) ?? 0) + 1);
  }
  return profiles;
}

function aggregateRefs(lists, score) {
  const merged = new Map();
  for (const list of lists) {
    for (const item of list) {
      const current = merged.get(item.id);
      if (!current) merged.set(item.id, { ...item, runs: 1 });
      else {
        current.similarity += item.similarity;
        current.overlap += item.overlap;
        current.priorityMatched += item.priorityMatched;
        current.priorityConfidence += item.priorityConfidence;
        current.runs += 1;
      }
    }
  }
  return [...merged.values()].map((item) => ({ ...item, similarity: item.similarity / item.runs, overlap: item.overlap / item.runs, priorityMatched: item.priorityMatched / item.runs, priorityConfidence: item.priorityConfidence / item.runs })).sort((a, b) => score(b) - score(a)).map(({ runs, ...item }) => item);
}

function computeVnRecommendations(params, includeSpoiler, selectedVnIdSet, selectedVns, activePriorityTags, negativePriorityTagIds) {
  if (!params.selectedVnIds.length) return [];
  const rounds = Math.max(1, Math.floor(params.profileSampleRounds || 1));
  const negativeVnIdSet = new Set(params.negativeSelectedVnIds);
  const exclusionVisibleTagIds = new Set([...activePriorityTags, ...negativePriorityTagIds]);
  const activeVnProfiles = buildDistinctProfiles(rounds, (round, coverageCounts) => buildActiveVnProfile(params.selectedVnIds, params.sampleWeights, params.negativeSelectedVnIds, params.negativeSampleWeights, includeSpoiler, activePriorityTags, negativePriorityTagIds, params.tagLimit, round, coverageCounts));
  const lists = [];
  for (const activeVnProfile of activeVnProfiles) {
    lists.push(priorityBucketedResults(data.vns.filter((vn) => !selectedVnIdSet.has(vn.id) && !negativeVnIdSet.has(vn.id) && vn.votes >= params.minVotes && !isSameCompanyPrefixDuplicate(vn, selectedVns)).filter((vn) => {
      if (!negativePriorityTagIds.size) return true;
      const vector = makeVector(vn.tags, tagMeta, 'tag', includeSpoiler, true, exclusionVisibleTagIds);
      return ![...negativePriorityTagIds].some((id) => vector.has(id));
    }).map((vn) => {
      const vector = omitUnprioritizedSpecialTags(makeVector(vn.tags, tagMeta, 'tag', includeSpoiler, true, activePriorityTags), tagMeta, activePriorityTags);
      const priorityMatched = priorityMatch(activePriorityTags, vector);
      const priorityTotal = activePriorityTags.size;
      const priorityConfidence = priorityTotal ? priorityMatched / priorityTotal : 1;
      const similarity = vectorScore(activeVnProfile, vector) * (priorityTotal ? 0.65 + priorityConfidence * 0.35 : 1);
      return { id: vn.id, similarity, overlap: overlap(activeVnProfile, vector), priorityMatched, priorityTotal, priorityConfidence, rating: vn.rating, votes: vn.votes };
    }).filter((vn) => vn.similarity > 0), activePriorityTags.size, (vn) => vn.similarity * 100 + vn.rating / 10 + Math.log10(vn.votes || 1)));
  }
  return aggregateRefs(lists, (vn) => vn.similarity * 100 + vn.rating / 10 + Math.log10(vn.votes || 1));
}

function computeCharacterRecommendations(params, includeSpoiler, selectedCharacterIdSet, activePriorityTraits, negativePriorityTraitIds) {
  if (!params.selectedCharacterIds.length) return [];
  const rounds = Math.max(1, Math.floor(params.profileSampleRounds || 1));
  const negativeCharacterIdSet = new Set(params.negativeSelectedCharacterIds);
  const exclusionVisibleTraitIds = new Set([...activePriorityTraits, ...negativePriorityTraitIds]);
  const sampleProfiles = params.selectedCharacterIds.map((id) => characterById.get(id)).filter(Boolean).map((character) => makeVector(character.traits, traitMeta, 'trait', includeSpoiler, true, activePriorityTraits));
  const activeCharacterProfiles = buildDistinctProfiles(rounds, (round, coverageCounts) => buildActiveCharacterProfile(params.selectedCharacterIds, params.sampleWeights, params.negativeSelectedCharacterIds, params.negativeSampleWeights, includeSpoiler, activePriorityTraits, negativePriorityTraitIds, params.traitLimit, round, coverageCounts));
  const referenceDeveloperIds = selectedCharacterDeveloperIds(params.selectedCharacterIds);
  const lists = [];
  for (const activeCharacterProfile of activeCharacterProfiles) {
    const candidates = data.characters.filter((character) => !selectedCharacterIdSet.has(character.id) && !negativeCharacterIdSet.has(character.id) && characterHasQualifiedVn(character, params.minVotes)).filter((character) => {
      if (!negativePriorityTraitIds.size) return true;
      const vector = makeVector(character.traits, traitMeta, 'trait', includeSpoiler, true, exclusionVisibleTraitIds);
      return ![...negativePriorityTraitIds].some((id) => vector.has(id));
    }).map((character) => {
      const vector = makeVector(character.traits, traitMeta, 'trait', includeSpoiler, true, activePriorityTraits);
      const priorityMatched = priorityMatch(activePriorityTraits, vector);
      const priorityTotal = activePriorityTraits.size;
      const priorityConfidence = priorityTotal ? priorityMatched / priorityTotal : 1;
      const similarity = vectorScore(activeCharacterProfile, vector) * (priorityTotal ? 0.65 + priorityConfidence * 0.35 : 1);
      const companyBoost = characterCompanyBoost(character, referenceDeveloperIds);
      return { id: character.id, similarity, overlap: overlap(activeCharacterProfile, vector), priorityMatched, priorityTotal, priorityConfidence, score: character.score, character, vector, companyBoost };
    }).filter((character) => character.similarity > 0);
    const consensusBonuses = characterConsensusBonuses(candidates, sampleProfiles);
    lists.push(priorityBucketedResults(candidates.map((character) => ({ ...character, consensusBonus: consensusBonuses.get(character.id) ?? 0 })), activePriorityTraits.size, (character) => characterResultScore({ ...character.character, ...character }, params.preferCharacterAverage)));
  }
  return aggregateRefs(lists, (character) => characterResultScore({ ...character.character, ...character }, params.preferCharacterAverage));
}

function collectCandidateIndexes(groups, postings) {
  const indexes = new Set();
  for (const group of groups) for (const id of group.alternatives) for (const index of postings.get(id) ?? []) indexes.add(index);
  return indexes;
}

function metaChildrenMap(items) {
  const children = new Map();
  for (const item of items) {
    for (const parentId of item.parents ?? []) {
      const list = children.get(parentId) ?? [];
      list.push(item);
      children.set(parentId, list);
    }
  }
  return children;
}

function metaSearchDescendants(kind, item, children, includeSexual, includeSpoiler, includeBlocked, includeTechnical, path = new Set()) {
  if (path.has(item.id)) return [];
  const nextPath = new Set(path);
  nextPath.add(item.id);
  const result = [];
  for (const child of children.get(item.id) ?? []) {
    if (!metaAllowedByFilters(child, kind, includeSexual, includeSpoiler, includeBlocked, includeTechnical)) continue;
    result.push(child, ...metaSearchDescendants(kind, child, children, includeSexual, includeSpoiler, includeBlocked, includeTechnical, nextPath));
  }
  return result;
}

function metaSearchGroups(kind, selectedIds, items, meta, includeSexual, includeSpoiler, includeBlocked = true, includeTechnical = true) {
  const children = metaChildrenMap(items);
  return [...selectedIds].map((selectedId) => {
    const alternatives = new Set([selectedId]);
    const item = meta.get(selectedId);
    const includeSexualDescendants = includeSexual && item?.sexual === true;
    const includeBlockedDescendants = includeBlocked || item?.blocked === true;
    const includeTechnicalDescendants = includeTechnical || item?.tech === true;
    if (item) for (const child of metaSearchDescendants(kind, item, children, includeSexualDescendants, includeSpoiler, includeBlockedDescendants, includeTechnicalDescendants)) alternatives.add(child.id);
    return { selectedId, alternatives: [...alternatives] };
  });
}

function selectedSexualAlternativeIds(groups, meta) {
  const ids = new Set();
  for (const group of groups) {
    if (!meta.get(group.selectedId)?.sexual) continue;
    for (const id of group.alternatives) ids.add(id);
  }
  return [...ids];
}

function defaultParams(input) {
  const includeSpoiler = Boolean(input.includeSpoiler ?? input.showSpoiler ?? false);
  const tagSearchTags = uniqueNumbers(input.tagSearchTags ?? input.tags);
  const tagSearchTraits = uniqueNumbers(input.tagSearchTraits ?? input.traits);
  const excludedTagSearchTags = uniqueNumbers(input.excludedTagSearchTags ?? input.excludeTags);
  const excludedTagSearchTraits = uniqueNumbers(input.excludedTagSearchTraits ?? input.excludeTraits);
  const tagSearchTagGroupsSpoilerOff = metaSearchGroups('tag', new Set(tagSearchTags), data.tags, tagMeta, true, false, false, false);
  const tagSearchTagGroupsSpoilerOn = metaSearchGroups('tag', new Set(tagSearchTags), data.tags, tagMeta, true, true, false, false);
  const tagSearchTraitGroupsSpoilerOff = metaSearchGroups('trait', new Set(tagSearchTraits), data.traits, traitMeta, true, false);
  const tagSearchTraitGroupsSpoilerOn = metaSearchGroups('trait', new Set(tagSearchTraits), data.traits, traitMeta, true, true);
  const excludedTagSearchTagGroupsSpoilerOff = metaSearchGroups('tag', new Set(excludedTagSearchTags), data.tags, tagMeta, true, false, true, true);
  const excludedTagSearchTagGroupsSpoilerOn = metaSearchGroups('tag', new Set(excludedTagSearchTags), data.tags, tagMeta, true, true, true, true);
  const excludedTagSearchTraitGroupsSpoilerOff = metaSearchGroups('trait', new Set(excludedTagSearchTraits), data.traits, traitMeta, true, false);
  const excludedTagSearchTraitGroupsSpoilerOn = metaSearchGroups('trait', new Set(excludedTagSearchTraits), data.traits, traitMeta, true, true);
  return {
    selectedVnIds: uniqueNumbers(input.selectedVnIds ?? input.vns ?? input.games),
    selectedCharacterIds: uniqueNumbers(input.selectedCharacterIds ?? input.characters),
    negativeSelectedVnIds: uniqueNumbers(input.negativeSelectedVnIds ?? input.negativeVns ?? input.negativeGames),
    negativeSelectedCharacterIds: uniqueNumbers(input.negativeSelectedCharacterIds ?? input.negativeCharacters),
    sampleWeights: asArray(input.sampleWeights).map(Number).filter(Number.isFinite),
    negativeSampleWeights: asArray(input.negativeSampleWeights).map(Number).filter(Number.isFinite),
    activePriorityTags: uniqueNumbers(input.activePriorityTags ?? input.priorityTags),
    activePriorityTraits: uniqueNumbers(input.activePriorityTraits ?? input.priorityTraits),
    negativePriorityTagIds: uniqueNumbers(input.negativePriorityTagIds ?? input.negativePriorityTags),
    negativePriorityTraitIds: uniqueNumbers(input.negativePriorityTraitIds ?? input.negativePriorityTraits),
    tagLimit: Number(input.tagLimit ?? 60),
    traitLimit: Number(input.traitLimit ?? 60),
    profileSampleRounds: Number(input.profileSampleRounds ?? input.rounds ?? 6),
    includeSpoiler,
    tagSearchTags,
    tagSearchTraits,
    excludedTagSearchTags: [...new Set((includeSpoiler ? excludedTagSearchTagGroupsSpoilerOn : excludedTagSearchTagGroupsSpoilerOff).flatMap((group) => group.alternatives))],
    excludedTagSearchTraits: [...new Set((includeSpoiler ? excludedTagSearchTraitGroupsSpoilerOn : excludedTagSearchTraitGroupsSpoilerOff).flatMap((group) => group.alternatives))],
    tagSearchTagGroupsSpoilerOff,
    tagSearchTagGroupsSpoilerOn,
    tagSearchTraitGroupsSpoilerOff,
    tagSearchTraitGroupsSpoilerOn,
    tagSearchSexualTagIdsSpoilerOff: selectedSexualAlternativeIds(tagSearchTagGroupsSpoilerOff, tagMeta),
    tagSearchSexualTagIdsSpoilerOn: selectedSexualAlternativeIds(tagSearchTagGroupsSpoilerOn, tagMeta),
    tagSearchSexualTraitIdsSpoilerOff: selectedSexualAlternativeIds(tagSearchTraitGroupsSpoilerOff, traitMeta),
    tagSearchSexualTraitIdsSpoilerOn: selectedSexualAlternativeIds(tagSearchTraitGroupsSpoilerOn, traitMeta),
    minVotes: Number(input.minVotes ?? 0),
    tagRoleFilter: { ...defaultRoleFilter(), ...(input.tagRoleFilter ?? input.roleFilter ?? {}) },
    preferCharacterAverage: Boolean(input.preferCharacterAverage ?? true),
    resultSort: input.resultSort ?? input.sort ?? 'relevance',
    sortDirection: input.sortDirection ?? input.direction ?? 'desc'
  };
}

function computeVariant(params, includeSpoiler) {
  const selectedVnIdSet = new Set(params.selectedVnIds);
  const selectedCharacterIdSet = new Set(params.selectedCharacterIds);
  const selectedVns = params.selectedVnIds.map((id) => vnById.get(id)).filter(Boolean);
  const activePriorityTags = new Set(params.activePriorityTags);
  const activePriorityTraits = new Set(params.activePriorityTraits);
  const negativePriorityTagIds = new Set(params.negativePriorityTagIds ?? []);
  const negativePriorityTraitIds = new Set(params.negativePriorityTraitIds ?? []);
  const excludedTagSearchTagIds = new Set(params.excludedTagSearchTags ?? []);
  const excludedTagSearchTraitIds = new Set(params.excludedTagSearchTraits ?? []);
  const tagSearchTagGroups = includeSpoiler ? params.tagSearchTagGroupsSpoilerOn : params.tagSearchTagGroupsSpoilerOff;
  const tagSearchTraitGroups = includeSpoiler ? params.tagSearchTraitGroupsSpoilerOn : params.tagSearchTraitGroupsSpoilerOff;
  const tagSearchTagAlternativeIds = new Set(params.tagSearchTags);
  for (const group of tagSearchTagGroups) for (const id of group.alternatives) tagSearchTagAlternativeIds.add(id);
  const tagSearchIndex = includeSpoiler ? tagSearchIndexSpoilerOn : tagSearchIndexSpoilerOff;
  const tagSearchVnCandidates = !tagSearchTagGroups.length || !tagSearchIndex ? [] : [...collectCandidateIndexes(tagSearchTagGroups, tagSearchIndex.postings)].map((index) => {
    const vn = data.vns[index];
    if (vn.votes < params.minVotes) return null;
    if (excludedTagSearchTagIds.size && [...excludedTagSearchTagIds].some((id) => tagSearchIndex.vectors[index].has(id))) return null;
    const vector = omitUnprioritizedSpecialTags(tagSearchIndex.vectors[index], tagMeta, tagSearchTagAlternativeIds);
    const priorityMatched = groupedPriorityMatch(tagSearchTagGroups, vector);
    const priorityTotal = tagSearchTagGroups.length;
    const priorityConfidence = groupedMetaConfidence(tagSearchTagGroups, vector);
    const similarity = groupedMetaScore(tagSearchTagGroups, vector) * (0.65 + priorityConfidence * 0.35);
    return similarity > 0 ? { id: vn.id, similarity, overlap: priorityMatched, priorityMatched, priorityTotal, priorityConfidence, rating: vn.rating, votes: vn.votes } : null;
  }).filter(Boolean);
  const traitSearchIndex = includeSpoiler ? traitSearchIndexSpoilerOn : traitSearchIndexSpoilerOff;
  const tagSearchCharacterCandidates = !tagSearchTraitGroups.length || !traitSearchIndex ? [] : [...collectCandidateIndexes(tagSearchTraitGroups, traitSearchIndex.postings)].map((index) => {
    const character = data.characters[index];
    if (!characterHasQualifiedVn(character, params.minVotes, params.tagRoleFilter)) return null;
    if (excludedTagSearchTraitIds.size && [...excludedTagSearchTraitIds].some((id) => traitSearchIndex.vectors[index].has(id))) return null;
    const vector = traitSearchIndex.vectors[index];
    const priorityMatched = groupedPriorityMatch(tagSearchTraitGroups, vector);
    const priorityTotal = tagSearchTraitGroups.length;
    const priorityConfidence = groupedMetaConfidence(tagSearchTraitGroups, vector);
    const similarity = groupedMetaScore(tagSearchTraitGroups, vector) * (0.65 + priorityConfidence * 0.35);
    return similarity > 0 ? { id: character.id, similarity, overlap: priorityMatched, priorityMatched, priorityTotal, priorityConfidence, score: character.score, character } : null;
  }).filter(Boolean);
  const mixedTagResults = (() => {
    if (!params.tagSearchTags.length || !params.tagSearchTraits.length) return [];
    const vnMatches = new Map(tagSearchVnCandidates.filter((vn) => vn.priorityMatched === vn.priorityTotal).map((vn) => [vn.id, vn]));
    if (!vnMatches.size) return [];
    return tagSearchCharacterCandidates.filter((character) => character.priorityMatched === character.priorityTotal).map((character) => {
      const source = characterById.get(character.id);
      if (!source) return null;
      const vn = [...characterRoleFilteredVnIds(source, params.tagRoleFilter)].map((id) => vnMatches.get(id)).filter(Boolean).sort((a, b) => a.id - b.id)[0];
      return vn ? { vnId: vn.id, characterId: character.id, similarity: (vn.similarity + character.similarity) / 2, priorityMatched: vn.priorityMatched + character.priorityMatched, priorityTotal: vn.priorityTotal + character.priorityTotal, priorityConfidence: (vn.priorityConfidence * vn.priorityTotal + character.priorityConfidence * character.priorityTotal) / (vn.priorityTotal + character.priorityTotal) } : null;
    }).filter(Boolean).sort((a, b) => b.similarity - a.similarity);
  })();
  const vnRecommendations = computeVnRecommendations(params, includeSpoiler, selectedVnIdSet, selectedVns, activePriorityTags, negativePriorityTagIds);
  const characterRecommendations = computeCharacterRecommendations(params, includeSpoiler, selectedCharacterIdSet, activePriorityTraits, negativePriorityTraitIds);
  return {
    vnRecommendations: sortVnRefs(vnRecommendations, params.resultSort, params.sortDirection),
    characterRecommendations: sortCharacterRefs(characterRecommendations, params.resultSort, params.sortDirection, params.preferCharacterAverage),
    tagSearchVnResults: sortVnRefs(priorityBucketedResults(tagSearchVnCandidates, tagSearchTagGroups.length, (vn) => vn.similarity * 100 + vn.rating / 10 + Math.log10(vn.votes || 1)), params.resultSort, params.sortDirection),
    tagSearchCharacterResults: sortCharacterRefs(priorityBucketedResults(tagSearchCharacterCandidates, tagSearchTraitGroups.length, (character) => character.similarity * 100 + (params.preferCharacterAverage ? characterAverageScore(character.character) / 10 : character.score / 100)), params.resultSort, params.sortDirection, params.preferCharacterAverage),
    mixedTagResults: sortMixedRefs(mixedTagResults, params.resultSort, params.sortDirection, params.preferCharacterAverage)
  };
}

function metaName(metaItem, language = 'zh', showSexual = true) {
  if (metaItem.sexual && !showSexual) return 'R18 hidden';
  if (language === 'zh') return metaItem.nameZh ?? metaItem.nameJa ?? metaItem.name ?? '';
  if (language === 'ja') return metaItem.nameJa ?? metaItem.nameZh ?? metaItem.name ?? '';
  return metaItem.name ?? '';
}

function splitAliases(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value ?? '').split('\n').map((item) => item.trim()).filter(Boolean);
}

function itemMeta(id, kind, language = 'origin', detail = false) {
  const meta = kind === 'tag' ? tagMeta : traitMeta;
  const item = meta.get(id);
  if (!item) return { id, vndbid: kind === 'tag' ? `g${id}` : `i${id}` };
  const result = {
    id: item.id,
    vndbid: kind === 'tag' ? `g${item.id}` : `i${item.id}`,
    title: item.name
  };
  if (detail) {
    result.description = item.description ?? null;
    result.aliases = splitAliases(item.alias);
    result.sexual = Boolean(item.sexual);
    result.defaultspoil = item.defaultspoil ?? 0;
    result.searchable = Boolean(item.searchable);
    result.applicable = Boolean(item.applicable);
    result.parents = item.parents ?? [];
    result.cat = item.cat;
    result.group = item.group ?? null;
    result.blocked = Boolean(item.blocked);
    result.tech = Boolean(item.tech);
    result.name = metaName(item, language, true);
    result.originalTitle = item.name;
    result.originalDescription = item.description ?? null;
    result.nameEn = item.name;
    result.nameZh = item.nameZh;
    result.nameJa = item.nameJa;
    result.descriptionZh = item.descriptionZh;
    result.descriptionJa = item.descriptionJa;
  }
  return result;
}

function vnTagFields(vn, detail = false) {
  return vn.tags.map((item) => {
    const result = {
      id: item[0],
      vndbid: `g${item[0]}`,
      name: itemMeta(item[0], 'tag').title,
      rating: item[1],
      spoiler: item[2] ?? 0
    };
    if (detail) {
      result.voteCount = item[4] ?? null;
      result.meta = itemMeta(item[0], 'tag', 'origin', true);
    }
    return result;
  });
}

function characterTraitFields(character, detail = false) {
  return character.traits.map((item) => {
    const result = {
      id: item[0],
      vndbid: `i${item[0]}`,
      name: itemMeta(item[0], 'trait').title,
      spoiler: item[1] ?? 0
    };
    if (detail) result.meta = itemMeta(item[0], 'trait', 'origin', true);
    return result;
  });
}

function slimVn(vn, extra = {}, detail = false) {
  const result = {
    id: vn.id,
    vndbid: `v${vn.id}`,
    title: vn.title,
    original: vn.original,
    aliases: splitAliases(vn.aliases),
    tags: vnTagFields(vn, detail),
    rating: vn.rating,
    votes: vn.votes,
    image: vn.image,
    developers: vn.developers.map((item) => ({ id: item.id, name: item.name, original: item.original, type: item.type, lang: item.lang })),
    ...extra
  };
  if (detail) {
    result.aliasText = vn.aliases;
    result.average = vn.average;
    result.publishers = vn.publishers.map((item) => ({ id: item.id, name: item.name, original: item.original, type: item.type, lang: item.lang }));
  }
  return result;
}

function slimCharacter(character, extra = {}, detail = false) {
  const result = {
    id: character.id,
    vndbid: `c${character.id}`,
    name: character.name,
    original: character.original,
    aliases: splitAliases(character.aliases),
    traits: characterTraitFields(character, detail),
    image: character.image,
    sex: character.sex,
    gender: character.gender,
    birthday: character.birthday,
    score: character.score,
    vns: character.vns.map(([id, role, spoiler]) => ({ id, vndbid: `v${id}`, role, spoiler, title: vnById.get(id)?.title ?? null })),
    ...extra
  };
  if (detail) {
    result.blood = character.blood;
    result.bust = character.bust;
    result.waist = character.waist;
    result.hip = character.hip;
  }
  return result;
}

function exactSearchMatch(value, query) {
  if (!value) return false;
  const field = text(value);
  const compactField = normalizeTitle(value);
  const compactQuery = normalizeTitle(query);
  return field === query || Boolean(compactField && compactField === compactQuery);
}

function exactSearchRank(primaryValues, aliasValues, query) {
  if (primaryValues.some((value) => exactSearchMatch(value, query))) return 2;
  if (aliasValues.some((value) => exactSearchMatch(value, query))) return 1;
  return 0;
}

function vnExactSearchRank(vn, query) {
  if (`v${vn.id}` === query) return 3;
  return exactSearchRank([vn.title, vn.original], vn.aliases.split('\n').map((alias) => alias.trim()).filter(Boolean), query);
}

function vnSearchRank(vn, query) {
  const title = text(vn.title);
  const original = text(vn.original ?? '');
  const aliases = vn.aliases.split('\n').map(text).filter(Boolean);
  if (`v${vn.id}` === query) return 100;
  if (title === query || original === query || aliases.includes(query)) return 90;
  if (title.startsWith(query) || original.startsWith(query) || aliases.some((alias) => alias.startsWith(query))) return 80;
  if (title.includes(query) || original.includes(query) || aliases.some((alias) => alias.includes(query))) return 70;
  if (vn.search.includes(query)) return 10;
  return 0;
}

function compareVnScore(a, b) {
  return b.rating - a.rating || b.votes - a.votes || b.average - a.average;
}

function compareVnSearchResult(query) {
  return (a, b) => vnExactSearchRank(b, query) - vnExactSearchRank(a, query) || vnSearchRank(b, query) - vnSearchRank(a, query) || compareVnScore(a, b) || a.id - b.id;
}

function characterExactSearchRank(character, query) {
  if (`c${character.id}` === query) return 3;
  return exactSearchRank([character.name, character.original], character.aliases, query);
}

function characterSearchMatch(character, query) {
  return characterExactSearchRank(character, query) > 0 || character.search.includes(query);
}

function compareCharacterSearchResult(query) {
  return (a, b) => characterExactSearchRank(b, query) - characterExactSearchRank(a, query) || b.score - a.score || a.id - b.id;
}

function characterDisplayScore(character, preferAverage = false) {
  return preferAverage ? characterAverageScore(character) * 10 + character.score / 100 : character.score;
}

function searchItems(input) {
  const mode = input.mode ?? input.kind ?? 'vn';
  const q = text(input.name ?? input.query ?? input.q);
  const limit = Math.max(1, Number(input.limit ?? input.n ?? 20));
  const detail = Boolean(input.detail ?? false);
  if (!q) return { mode, query: q, results: [] };
  if (mode === 'vn' || mode === 'game') {
    const results = isVnId(q) ? data.vns.filter((vn) => vn.id === idOf(q)) : data.vns.filter((vn) => vnSearchRank(vn, q) > 0).sort(compareVnSearchResult(q));
    return { mode: 'vn', query: q, results: results.slice(0, limit).map((vn) => slimVn(vn, { searchRank: vnSearchRank(vn, q), exactRank: vnExactSearchRank(vn, q) }, detail)) };
  }
  if (isCharId(q)) return { mode: 'character', query: q, results: data.characters.filter((character) => character.id === idOf(q)).slice(0, limit).map((character) => slimCharacter(character, { exactRank: characterExactSearchRank(character, q) }, detail)) };
  const directCharacters = data.characters.filter((character) => characterSearchMatch(character, q)).sort(compareCharacterSearchResult(q));
  if (directCharacters.length || mode === 'characterOnly') return { mode: 'character', query: q, results: directCharacters.slice(0, limit).map((character) => slimCharacter(character, { exactRank: characterExactSearchRank(character, q) }, detail)) };
  const matchedVns = data.vns.filter((vn) => vnSearchRank(vn, q) > 0).sort(compareVnSearchResult(q)).slice(0, 30);
  const matchedVnRank = new Map(matchedVns.map((vn, index) => [vn.id, matchedVns.length - index]));
  const fallback = data.characters.filter((character) => character.vns.some(([id]) => matchedVnRank.has(id))).sort((a, b) => Math.max(0, ...b.vns.map(([id]) => matchedVnRank.get(id) ?? 0)) * 1000 + characterDisplayScore(b, false) - (Math.max(0, ...a.vns.map(([id]) => matchedVnRank.get(id) ?? 0)) * 1000 + characterDisplayScore(a, false)));
  return { mode: 'character', query: q, fallbackFromVnSearch: true, results: fallback.slice(0, limit).map((character) => slimCharacter(character, {}, detail)) };
}

function searchMeta(input) {
  const kind = input.kind === 'trait' ? 'trait' : 'tag';
  const q = text(input.name ?? input.query ?? input.q);
  const limit = Math.max(1, Number(input.limit ?? input.n ?? 30));
  const meta = kind === 'tag' ? data.tags : data.traits;
  const results = meta.filter((item) => {
    if (!q) return true;
    const names = [item.name, item.nameZh, item.nameJa, item.alias, item.description, item.descriptionZh, item.descriptionJa].filter(Boolean).join('\n').toLocaleLowerCase();
    return String(item.id) === q || names.includes(q);
  }).sort((a, b) => metaName(a).localeCompare(metaName(b))).slice(0, limit).map((item) => itemMeta(item.id, kind));
  return { kind, query: q, results };
}

function recommendations(input) {
  const params = defaultParams(input);
  const variant = computeVariant(params, params.includeSpoiler);
  const limit = Math.max(1, Number(input.limit ?? input.n ?? 20));
  const detail = Boolean(input.detail ?? false);
  return {
    params: { ...params, tagRoleFilter: params.tagRoleFilter },
    vnRecommendations: variant.vnRecommendations.slice(0, limit).map((item) => slimVn(vnById.get(item.id), item, detail)),
    characterRecommendations: variant.characterRecommendations.slice(0, limit).map((item) => slimCharacter(characterById.get(item.id), item, detail)),
    tagSearchVnResults: variant.tagSearchVnResults.slice(0, limit).map((item) => slimVn(vnById.get(item.id), item, detail)),
    tagSearchCharacterResults: variant.tagSearchCharacterResults.slice(0, limit).map((item) => slimCharacter(characterById.get(item.id), item, detail)),
    mixedTagResults: variant.mixedTagResults.slice(0, limit).map((item) => ({ ...item, vn: slimVn(vnById.get(item.vnId), {}, detail), character: slimCharacter(characterById.get(item.characterId), {}, detail) }))
  };
}

function pickBestLocalTarget(input) {
  const value = input.id ?? input.vndbid ?? input.name ?? input.query ?? input.q;
  const raw = String(value ?? '').trim();
  const mode = input.mode ?? input.kind ?? (isCharId(raw) ? 'character' : 'vn');
  if (!raw) throw new Error('detail action requires name/query/id/vndbid');
  if (isVnId(raw)) {
    const vn = vnById.get(idOf(raw));
    if (!vn) throw new Error(`VN not found: ${raw}`);
    return { type: 'vn', id: vn.id, local: slimVn(vn) };
  }
  if (isCharId(raw)) {
    const character = characterById.get(idOf(raw));
    if (!character) throw new Error(`Character not found: ${raw}`);
    return { type: 'character', id: character.id, local: slimCharacter(character) };
  }
  const found = searchItems({ action: 'search', mode, name: raw, limit: 1, detail: Boolean(input.detail ?? false) }).results?.[0];
  if (!found) throw new Error(`No local search result for: ${raw}`);
  return { type: found.vndbid?.startsWith('c') ? 'character' : 'vn', id: found.id, local: found };
}

function vndbImageUrlFromId(imageId) {
  if (!imageId) return null;
  if (/^https?:\/\//i.test(imageId)) return imageId;
  const value = String(imageId);
  const numeric = value.replace(/^cv/i, '');
  return /^\d+$/.test(numeric) ? `https://t.vndb.org/cv/${numeric}.jpg` : null;
}

function extensionFromContentType(contentType, fallback = '.jpg') {
  const type = String(contentType ?? '').toLocaleLowerCase();
  if (type.includes('png')) return '.png';
  if (type.includes('webp')) return '.webp';
  if (type.includes('gif')) return '.gif';
  if (type.includes('jpeg') || type.includes('jpg')) return '.jpg';
  return fallback;
}

async function downloadImageToCache(url, key) {
  if (!url) return null;
  await mkdir(IMAGE_CACHE_DIR, { recursive: true });
  const safeKey = String(key).replace(/[^a-z0-9_-]/gi, '_');
  const existing = ['.jpg', '.png', '.webp', '.gif'].map((ext) => join(IMAGE_CACHE_DIR, `${safeKey}${ext}`)).find((path) => existsSync(path));
  if (existing) return { url, localPath: existing, cached: true };
  const response = await fetch(url, { headers: { accept: 'image/avif,image/webp,image/png,image/jpeg,image/*' } });
  if (!response.ok) throw new Error(`Image download failed ${url}: HTTP ${response.status}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  const ext = extensionFromContentType(response.headers.get('content-type'));
  const localPath = join(IMAGE_CACHE_DIR, `${safeKey}${ext}`);
  await writeFile(localPath, buffer);
  return { url, localPath, cached: false, bytes: buffer.length };
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map((item) => stableJson(item)).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sameJsonValue(left, right) {
  return stableJson(left) === stableJson(right);
}

function collectStrings(value, strings = new Set()) {
  if (typeof value === 'string') {
    const normalized = value.trim();
    if (normalized) strings.add(normalized);
  } else if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, strings);
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) collectStrings(item, strings);
  }
  return strings;
}

function pruneDuplicateStrings(value, remoteStrings) {
  if (typeof value === 'string') return remoteStrings.has(value.trim()) ? undefined : value;
  if (Array.isArray(value)) {
    const items = value.map((item) => pruneDuplicateStrings(item, remoteStrings)).filter((item) => item !== undefined);
    return items.length ? items : undefined;
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value).map(([key, item]) => [key, pruneDuplicateStrings(item, remoteStrings)]).filter(([, item]) => item !== undefined);
    return entries.length ? Object.fromEntries(entries) : undefined;
  }
  return value;
}

function omitDuplicateLocalFields(local, remote) {
  if (!local || typeof local !== 'object' || Array.isArray(local) || !remote || typeof remote !== 'object' || Array.isArray(remote)) return local;
  const remoteStrings = collectStrings(remote);
  return Object.fromEntries(Object.entries(local).map(([key, value]) => [key, Object.hasOwn(remote, key) && sameJsonValue(value, remote[key]) ? undefined : pruneDuplicateStrings(value, remoteStrings)]).filter(([, value]) => value !== undefined));
}

async function vndbApiDetail(input) {
  const target = pickBestLocalTarget(input);
  const downloadImage = Boolean(input.downloadImage ?? input.image ?? true);
  const localImageUrl = target.type === 'vn' ? vndbImageUrlFromId(target.local.image) : null;
  const fields = target.type === 'vn'
    ? input.fields ?? 'id,title,alttitle,aliases,olang,released,languages,platforms,image.url,image.sexual,image.violence,image.votecount,image.dims,length,length_minutes,description,rating,votecount,tags.rating,tags.spoiler,tags.lie,tags.id,tags.name,developers.id,developers.name,relations.id,relations.relation,relations.title'
    : input.fields ?? 'id,name,original,aliases,description,image.url,image.sexual,image.violence,image.votecount,image.dims,sex,blood_type,height,weight,bust,waist,hips,birthday,age,traits.id,traits.name,traits.spoiler,traits.lie,vns.id,vns.title,vns.role,vns.spoiler';
  const endpoint = target.type === 'vn' ? 'vn' : 'character';
  const api = await postJson(`${VNDB_API_BASE}/${endpoint}`, {
    filters: ['id', '=', target.type === 'vn' ? `v${target.id}` : `c${target.id}`],
    fields,
    results: 1
  });
  const remote = api?.results?.[0] ?? null;
  const local = omitDuplicateLocalFields(target.local, remote);
  const apiImageUrl = remote?.image?.url ?? null;
  const imageUrl = apiImageUrl ?? localImageUrl;
  let imageCache = null;
  let imageCacheError = null;
  if (downloadImage && imageUrl) {
    try {
      imageCache = await downloadImageToCache(imageUrl, `${target.type}-${target.id}`);
    } catch (error) {
      imageCacheError = String(error?.message || error);
    }
  }
  return {
    target: { type: target.type, id: target.id, vndbid: target.type === 'vn' ? `v${target.id}` : `c${target.id}` },
    local,
    vndbApi: remote,
    image: imageUrl ? { url: imageUrl, cache: imageCache, cacheError: imageCacheError } : null
  };
}

function classify(input) {
  const kind = input.kind === 'trait' ? 'trait' : 'tag';
  const ids = uniqueNumbers(input.ids ?? input.tags ?? input.traits);
  const includeSpoiler = Boolean(input.includeSpoiler ?? false);
  const groups = metaSearchGroups(kind, new Set(ids), kind === 'tag' ? data.tags : data.traits, kind === 'tag' ? tagMeta : traitMeta, true, includeSpoiler, kind !== 'tag' || Boolean(input.includeBlocked ?? true), kind !== 'tag' || Boolean(input.includeTechnical ?? true));
  return { kind, groups: groups.map((group) => ({ selected: itemMeta(group.selectedId, kind), alternatives: group.alternatives.map((id) => itemMeta(id, kind)) })) };
}

async function loadDataFromDisk() {
  const raw = JSON.parse(await readFile(DATA_FILE, 'utf8'));
  data = decodeLocalData(raw);
  tagMeta = new Map(data.tags.map((tag) => [tag.id, tag]));
  traitMeta = new Map(data.traits.map((trait) => [trait.id, trait]));
  vnById = new Map(data.vns.map((vn) => [vn.id, vn]));
  characterById = new Map(data.characters.map((character) => [character.id, character]));
  tagSearchIndexSpoilerOff = buildTagSearchIndex(false);
  tagSearchIndexSpoilerOn = buildTagSearchIndex(true);
  traitSearchIndexSpoilerOff = buildTraitSearchIndex(false);
  traitSearchIndexSpoilerOn = buildTraitSearchIndex(true);
  manifest = await readLocalManifest();
  lastDataLoad = new Date().toISOString();
}

async function ensureData(forceUpdate = false) {
  if (loadingPromise) return loadingPromise;
  loadingPromise = (async () => {
    if (forceUpdate || !existsSync(DATA_FILE)) await downloadLatestData(forceUpdate);
    else manifest = await readLocalManifest();
    await loadDataFromDisk();
    return data;
  })().finally(() => {
    loadingPromise = null;
  });
  return loadingPromise;
}

async function checkForUpdates(force = false) {
  const result = await downloadLatestData(force);
  if (result.updated || !data) await loadDataFromDisk();
  return result;
}

async function handleAction(payload) {
  await ensureData(false);
  const action = payload.action ?? payload.type ?? 'status';
  if (action === 'status') {
    const dataStat = existsSync(DATA_FILE) ? await stat(DATA_FILE) : null;
    return { ok: true, action, generatedAt: data?.generatedAt, buildDateUtc8: data?.buildDateUtc8, manifestGeneratedAt: manifest?.generatedAt, manifestSha256: manifest?.sha256, vns: data?.vns.length ?? 0, characters: data?.characters.length ?? 0, tags: data?.tags.length ?? 0, traits: data?.traits.length ?? 0, dataBytes: dataStat?.size ?? 0, lastUpdateCheck, lastDataLoad };
  }
  if (action === 'update') return { ok: true, action, ...(await checkForUpdates(Boolean(payload.force))) };
  if (action === 'search') return { ok: true, action, ...searchItems(payload) };
  if (action === 'metaSearch') return { ok: true, action, ...searchMeta(payload) };
  if (action === 'detail' || action === 'vndbDetail' || action === 'apiDetail') return { ok: true, action, ...(await vndbApiDetail(payload)) };
  if (action === 'classify') return { ok: true, action, ...classify(payload) };
  if (action === 'recommend' || action === 'tagSearch' || action === 'compute') return { ok: true, action, ...recommendations(payload) };
  throw new Error(`Unknown action: ${action}`);
}

const server = createServer(async (request, response) => {
  try {
    if (request.method === 'OPTIONS') return jsonResponse(response, 204, {});
    if (request.method === 'GET' && request.url?.startsWith('/health')) return jsonResponse(response, 200, await handleAction({ action: 'status' }));
    if (request.method !== 'POST') return jsonResponse(response, 404, { ok: false, error: 'Use POST JSON' });
    const payload = await readRequestJson(request);
    const result = await handleAction(payload);
    return jsonResponse(response, 200, result);
  } catch (error) {
    return jsonResponse(response, 500, { ok: false, error: String(error?.stack || error?.message || error) });
  }
});

const cliArgs = new Set(process.argv.slice(2));
const cliUpdateOnly = cliArgs.has('--update');
const cliForce = cliArgs.has('--force');

if (cliUpdateOnly) {
  const result = await checkForUpdates(cliForce);
  console.log(JSON.stringify({ ok: true, mode: 'update', updated: result.updated, manifestSha256: manifest?.sha256, generatedAt: data?.generatedAt, lastUpdateCheck, lastDataLoad, dataDir: DATA_DIR }));
} else {
  await ensureData(false);
  setInterval(() => checkForUpdates(false).catch((error) => console.error(new Date().toISOString(), String(error?.stack || error))), UPDATE_INTERVAL_MS).unref();
  server.listen(PORT, '127.0.0.1', () => {
    console.log(JSON.stringify({ ok: true, url: `http://127.0.0.1:${PORT}`, dataDir: DATA_DIR, generatedAt: data?.generatedAt, manifestSha256: manifest?.sha256 }));
  });
}
