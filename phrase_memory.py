"""Explicit source-backed preferences, reversible acceptance, and versioned drift guard."""
import hashlib,json,math,time

class PhraseMemory:
    def __init__(self,library):
        self.library=library;self.db=library.db
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='user_phrase_memory'").fetchone():library.backup()
        self.db.executescript('''CREATE TABLE IF NOT EXISTS user_phrase_memory(context_key TEXT,phrase TEXT,region TEXT,modality TEXT,source_id TEXT,accepted_count INTEGER DEFAULT 0,rejected_count INTEGER DEFAULT 0,last_used REAL,PRIMARY KEY(context_key,phrase,region,modality,source_id));
        CREATE TABLE IF NOT EXISTS phrase_events(id INTEGER PRIMARY KEY,context_key TEXT,phrase TEXT,region TEXT,modality TEXT,source_id TEXT,accepted INTEGER,active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS rank_versions(id INTEGER PRIMARY KEY,weights TEXT,metrics TEXT,active INTEGER,created REAL);''')
        self.db.commit()
    def record(self,context,phrase,area,kind,source,accepted=True):
        if not self.library.ai.enabled('self_learning'):return None
        # Store a context digest and a public/verified source phrase, never a draft.
        key=hashlib.sha256(context.casefold().encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO user_phrase_memory VALUES(?,?,?,?,?,0,0,?)',(key,phrase,area,kind,source,time.time()))
            column='accepted_count' if accepted else 'rejected_count'
            old=self.db.execute('SELECT '+column+' FROM user_phrase_memory WHERE context_key=? AND phrase=? AND region=? AND modality=? AND source_id=?',(key,phrase,area,kind,source)).fetchone()[0]
            self.db.execute('UPDATE user_phrase_memory SET '+column+'=min('+column+'+1,100),last_used=? WHERE context_key=? AND phrase=? AND region=? AND modality=? AND source_id=?',(time.time(),key,phrase,area,kind,source))
            cur=self.db.execute('INSERT INTO phrase_events(context_key,phrase,region,modality,source_id,accepted,active) VALUES(?,?,?,?,?,?,?)',(key,phrase,area,kind,source,int(accepted),int(old<100)))
            self.db.execute('DELETE FROM phrase_events WHERE id NOT IN (SELECT id FROM phrase_events ORDER BY id DESC LIMIT 5000)')
        return cur.lastrowid
    def undo(self,event):
        row=self.db.execute('SELECT context_key,phrase,region,modality,source_id,accepted FROM phrase_events WHERE id=? AND active=1',(event,)).fetchone()
        if not row:return
        with self.db:
            column='accepted_count' if row[-1] else 'rejected_count'
            self.db.execute('UPDATE user_phrase_memory SET '+column+'=max(0,'+column+'-1) WHERE context_key=? AND phrase=? AND region=? AND modality=? AND source_id=?',row[:-1])
            self.db.execute('UPDATE phrase_events SET active=0 WHERE id=?',(event,))
    def boost(self,context,phrase,area,kind):
        key=hashlib.sha256(context.casefold().encode()).hexdigest()
        row=self.db.execute('SELECT sum(accepted_count),sum(rejected_count) FROM user_phrase_memory WHERE context_key=? AND phrase=? AND region=? AND modality=?',(key,phrase,area,kind)).fetchone()
        return min(3,math.log1p(row[0] or 0))-min(4,math.log1p(row[1] or 0))
    def activate_weights(self,weights,metrics):
        # Recompute a frozen shadow check; caller-supplied metrics cannot authorize activation.
        from rank_guard import validate
        allowed,metrics=validate(self.library.ai.ranker.weights,weights)
        if not allowed:return False
        self.library.backup()
        with self.db:
            self.db.execute('UPDATE rank_versions SET active=0')
            self.db.execute('INSERT INTO rank_versions(weights,metrics,active,created) VALUES(?,?,1,?)',(json.dumps(weights),json.dumps(metrics),time.time()))
            for feature,value in weights.items():self.db.execute('INSERT OR REPLACE INTO hybrid_weights VALUES(?,?)',(feature,value))
            self.db.execute('DELETE FROM rank_versions WHERE id NOT IN (SELECT id FROM rank_versions ORDER BY id DESC LIMIT 5)')
        self.library.ai.ranker.reload();return True
    def rollback(self,version):
        row=self.db.execute('SELECT weights FROM rank_versions WHERE id=?',(version,)).fetchone()
        if not row:return False
        self.library.backup()
        with self.db:
            self.db.execute('DELETE FROM hybrid_weights')
            self.db.executemany('INSERT INTO hybrid_weights VALUES(?,?)',json.loads(row[0]).items())
            self.db.execute('UPDATE rank_versions SET active=(id=?)',(version,))
        self.library.ai.ranker.reload();return True
    def clear(self):
        with self.db:
            self.db.execute('DELETE FROM user_phrase_memory');self.db.execute('DELETE FROM phrase_events')
