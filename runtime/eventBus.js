/**
* 🔥 runtime/eventBus.js
* Central Nervous System of ClawIntel.
* Pure pub/sub. No delays. No blocking.
* All agents subscribe and publish here.
*/

class EventBus {
  constructor() {
    this.subscribers = new Map();
    this.history = [];
    this.maxHistory = 1000;
  }

  /**
   * @param {string} eventType
   * @param {Function} callback
   * @returns {Function}
   */
  subscribe(eventType, callback) {
    if (!this.subscribers.has(eventType)) {
      this.subscribers.set(eventType, new Set());
    }
    this.subscribers.get(eventType).add(callback);

    // Return unsubscribe function
    return () => {
      this.subscribers.get(eventType)?.delete(callback);
    };
  }

  /**
   * Publish an event to all subscribers.
   * @param {string} eventType
   * @param {any} payload
   */
  publish(eventType, payload) {
    const event = {
      type: eventType,
      payload,
      timestamp: Date.now(),
    };

    // Store in history
    this.history.push(event);
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }

    // Notify all subscribers (async, non-blocking)
    const callbacks = this.subscribers.get(eventType);
    if (callbacks) {
      callbacks.forEach((cb) => {
        try {
          cb(payload);
        } catch (err) {
          console.error(`[eventBus] Error in subscriber for ${eventType}:`, err.message);
        }
      });
    }
  }

  /**
   * Publish and also broadcast to all WebSocket clients via stream
   * @param {string} eventType
   * @param {any} payload
   * @param {Function} wsBroadcast - optional external broadcaster
   */
  publishAndBroadcast(eventType, payload, wsBroadcast = null) {
    this.publish(eventType, payload);
    if (wsBroadcast) {
      wsBroadcast(eventType, payload);
    }
  }

  /**
   * Get recent history for a specific event type
   */
  getHistory(eventType, limit = 50) {
    return this.history
      .filter((e) => e.type === eventType)
      .slice(-limit)
      .map((e) => e.payload);
  }

  /**
   * Get all event types currently subscribed
   */
  getActiveEventTypes() {
    return Array.from(this.subscribers.keys());
  }
}

const eventBus = new EventBus();

export default eventBus;
export { EventBus };