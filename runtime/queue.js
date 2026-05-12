class EventQueue {
  constructor(eventBus, options = {}) {
    this.eventBus = eventBus;
    this.buffer = [];
    this.maxSize = options.maxSize || 500;
    this.flushInterval = options.flushInterval || 2000; // ms
    this.isFlushing = false;
    this.flushTimer = null;
  }

  /**
   * Buffer an event instead of publishing immediately.
   * Use this ONLY during overload conditions.
   */
  bufferEvent(eventType, payload) {
    if (this.buffer.length >= this.maxSize) {
      this.buffer.shift();
      console.warn('[queue] Buffer full — dropped oldest event');
    }

    this.buffer.push({ eventType, payload, bufferedAt: Date.now() });

    // Start flush timer if not already running
    if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => this.flush(), this.flushInterval);
    }
  }

  /**
   * Flush buffered events to eventBus
   */
  flush() {
    if (this.isFlushing || this.buffer.length === 0) {
      this.flushTimer = null;
      return;
    }

    this.isFlushing = true;
    const batch = [...this.buffer];
    this.buffer = [];

    console.log(`[queue] Flushing ${batch.length} buffered events`);

    batch.forEach(({ eventType, payload }) => {
      try {
        this.eventBus.publish(eventType, payload);
      } catch (err) {
        console.error(`[queue] Failed to flush ${eventType}:`, err.message);
      }
    });

    this.isFlushing = false;
    this.flushTimer = null;
  }

  /**
   * Get current buffer stats
   */
  getStats() {
    return {
      buffered: this.buffer.length,
      maxSize: this.maxSize,
      isFlushing: this.isFlushing,
    };
  }

  /**
   * Clear all buffered events
   */
  clear() {
    const count = this.buffer.length;
    this.buffer = [];
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    console.log(`[queue] Cleared ${count} buffered events`);
  }

  /**
   * Graceful shutdown
   */
  shutdown() {
    this.flush();
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
    }
    console.log('[queue] Queue shut down');
  }
}

export default EventQueue;
export { EventQueue };