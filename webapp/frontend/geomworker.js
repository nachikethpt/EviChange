/* Web Worker for ⚙ Tools: runs geomops.js off the page's main thread so the map stays usable.
 * Message in:  { id, op, args }      Messages out: { id, progress } … then { id, result } or { id, error }
 */
importScripts('/static/vendor/turf.min.js', '/static/geomops.js');

onmessage = ({ data: { id, op, args } }) => {
  try {
    if (!GEO_OPS[op]) throw new Error(`unknown operation ${op}`);
    const result = GEO_OPS[op](args, p => postMessage({ id, progress: p }));
    postMessage({ id, result });
  } catch (err) {
    postMessage({ id, error: err.message || String(err) });
  }
};
