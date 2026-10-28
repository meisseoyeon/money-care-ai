export function createTransactionApi(request) {
  return {
    async loadTransactions() {
      const items = [];
      let cursor = null;
      do {
        const page = await request(`/transactions${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
        items.push(...page.items);
        cursor = page.next_cursor;
      } while (cursor);
      return items;
    },
  };
}
