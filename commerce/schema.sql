CREATE TABLE IF NOT EXISTS tenants (
    tenant TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL,
    return_days INTEGER NOT NULL CHECK(return_days > 0), status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    tenant TEXT NOT NULL REFERENCES tenants(tenant), id TEXT NOT NULL, display TEXT NOT NULL,
    PRIMARY KEY(tenant,id)
);
CREATE TABLE IF NOT EXISTS products (
    tenant TEXT NOT NULL REFERENCES tenants(tenant), sku TEXT NOT NULL, title TEXT NOT NULL,
    category TEXT NOT NULL, brand TEXT NOT NULL, price INTEGER NOT NULL CHECK(price >= 0),
    stock INTEGER NOT NULL CHECK(stock >= 0), illustration TEXT NOT NULL, description TEXT NOT NULL,
    currency TEXT NOT NULL, PRIMARY KEY(tenant,sku)
);
CREATE TABLE IF NOT EXISTS orders (
    tenant TEXT NOT NULL, ref TEXT NOT NULL, customer TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('Confirmed','Packing','Dispatched','Delivered','Cancelled')),
    updated TEXT NOT NULL, delivered TEXT, preference TEXT NOT NULL, carrier TEXT, tracking TEXT,
    total INTEGER NOT NULL CHECK(total >= 0), currency TEXT NOT NULL,
    PRIMARY KEY(tenant,ref), FOREIGN KEY(tenant,customer) REFERENCES customers(tenant,id)
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(tenant,customer,ref);
CREATE TABLE IF NOT EXISTS items (
    tenant TEXT NOT NULL, order_ref TEXT NOT NULL, line TEXT NOT NULL, sku TEXT NOT NULL,
    title TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0), unit_price INTEGER NOT NULL,
    personalised INTEGER NOT NULL CHECK(personalised IN (0,1)), PRIMARY KEY(tenant,order_ref,line),
    FOREIGN KEY(tenant,order_ref) REFERENCES orders(tenant,ref),
    FOREIGN KEY(tenant,sku) REFERENCES products(tenant,sku)
);
CREATE TABLE IF NOT EXISTS refunds (
    tenant TEXT NOT NULL, ref TEXT NOT NULL, order_ref TEXT NOT NULL, status TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount >= 0), currency TEXT NOT NULL, updated TEXT NOT NULL,
    PRIMARY KEY(tenant,ref), FOREIGN KEY(tenant,order_ref) REFERENCES orders(tenant,ref)
);
CREATE TABLE IF NOT EXISTS returns (
    tenant TEXT NOT NULL, ref TEXT NOT NULL, order_ref TEXT NOT NULL, line TEXT NOT NULL,
    reason TEXT NOT NULL, resolution TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
    version TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(tenant,ref), UNIQUE(tenant,order_ref,line),
    FOREIGN KEY(tenant,order_ref,line) REFERENCES items(tenant,order_ref,line)
);
CREATE TABLE IF NOT EXISTS tickets (
    tenant TEXT NOT NULL, ref TEXT NOT NULL, customer TEXT NOT NULL, session TEXT NOT NULL,
    kind TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL, summary TEXT NOT NULL,
    order_ref TEXT, status TEXT NOT NULL CHECK(status IN ('Open','In progress','Resolved')),
    assigned TEXT, created TEXT NOT NULL, PRIMARY KEY(tenant,ref),
    FOREIGN KEY(tenant,customer) REFERENCES customers(tenant,id),
    FOREIGN KEY(tenant,order_ref) REFERENCES orders(tenant,ref)
);
CREATE INDEX IF NOT EXISTS idx_tickets_owner ON tickets(tenant,customer,ref);
CREATE UNIQUE INDEX IF NOT EXISTS idx_current_handoff ON tickets(tenant,session)
    WHERE kind='Handoff' AND status!='Resolved';
CREATE TABLE IF NOT EXISTS ticket_messages (
    tenant TEXT NOT NULL, ticket TEXT NOT NULL, id TEXT NOT NULL, actor TEXT NOT NULL,
    body TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(tenant,ticket,id),
    FOREIGN KEY(tenant,ticket) REFERENCES tickets(tenant,ref)
);
CREATE TABLE IF NOT EXISTS knowledge (
    tenant TEXT NOT NULL REFERENCES tenants(tenant), source TEXT NOT NULL, topic TEXT NOT NULL,
    title TEXT NOT NULL, version TEXT NOT NULL, effective TEXT NOT NULL, expires TEXT,
    state TEXT NOT NULL, keywords TEXT NOT NULL, passage TEXT NOT NULL,
    PRIMARY KEY(tenant,source,version)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge(tenant,state,effective);
CREATE TABLE IF NOT EXISTS operations (
    tenant TEXT NOT NULL REFERENCES tenants(tenant), token TEXT NOT NULL, actor TEXT NOT NULL,
    operation TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(tenant,token)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(tenant),
    actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
    outcome TEXT NOT NULL, correlation TEXT NOT NULL, time TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'Application audit is append only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'Application audit is append only'); END;
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, tenant TEXT NOT NULL REFERENCES tenants(tenant),
    session TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL, ms REAL, time TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_tenant ON activity(tenant,event);
