import { writeFileSync } from 'node:fs';

writeFileSync(new URL('./generated.json', import.meta.url), JSON.stringify({ total: 2 + 3 }, null, 2) + '\n');
