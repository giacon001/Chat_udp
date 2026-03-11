# 🐛 DEBUG: Mensagens não aparecem entre computadores diferentes

## 🔍 Problema Identificado

**Sintoma:** Você envia mensagem para seu colega, as setinhas confirmam envio/recebimento (✓✓), mas **você não vê as mensagens que ele envia de volta**.

## 🎯 Causa Raiz Identificada

### **PROBLEMA CRÍTICO na linha 300-302 do `chat_gui.py`:**

```python
def _processar(self, msg: Mensagem):
    with self._lock:
        if (msg.encaminhado and msg.encaminhado_por
                and msg.encaminhado_por in self._historico):
            chave = msg.encaminhado_por
        elif msg.remetente_nome in self._historico:  # ← PROBLEMA AQUI!
            chave = msg.remetente_nome
        else:
            chave = msg.remetente_nome
            self._historico[chave] = deque(maxlen=300)
            self._brutas[chave]    = deque(maxlen=50)
```

### 📌 O que acontece quando você configura os computadores:

**Computador A (seu):**
- Nome: `"MeuPC"`
- IP: `192.168.137.1`
- Porta: `5001`
- Vizinho configurado: `"PCColega"` em `192.168.137.2:5002`

**Computador B (colega):**
- Nome: `"PCColega"`
- IP: `192.168.137.2`
- Porta: `5002`
- Vizinho configurado: `"MeuPC"` em `192.168.137.1:5001`

### 🔴 Passo a passo do BUG:

1. **Inicialização do Computador A:**
   ```python
   self._historico = {
       "PCColega": deque(maxlen=300)  # ← Criado na inicialização
   }
   ```

2. **Você envia mensagem para "PCColega":**
   - ✅ Mensagem é enviada via UDP
   - ✅ Aparece no seu histórico como `{"tipo": "eu", ...}`
   - ✅ Colega recebe (por isso ele vê sua mensagem)

3. **Colega responde de volta:**
   - Mensagem UDP chega no seu computador
   - `_loop_escuta()` recebe o datagrama
   - `_processar()` é chamado com a mensagem

4. **AQUI ESTÁ O BUG:**
   ```python
   msg.remetente_nome = "PCColega"  # Nome do colega
   
   # A verificação:
   elif msg.remetente_nome in self._historico:  # ← "PCColega" ESTÁ no dicionário!
       chave = msg.remetente_nome  # chave = "PCColega"
   
   # A mensagem é armazenada:
   self._historico["PCColega"].append({"tipo": "deles", "msg": msg})
   ```

5. **Callback é disparado:**
   ```python
   self._callback_nova_msg("PCColega")  # ← chave correta
   ```

6. **GUI recebe o callback (`_processar_nova_msg`):**
   ```python
   def _processar_nova_msg(self, chave: str):
       # chave = "PCColega"
       viz_ativo = self.no.vizinhos[self._vizinho_ativo].nome
       # viz_ativo = "PCColega" (assumindo que você está na conversa dele)
       
       if chave == viz_ativo:  # ← "PCColega" == "PCColega" → TRUE!
           self._redesenhar_mensagens()  # ← DEVERIA redesenhar
   ```

## 🤔 Por que então não aparece?

### Hipóteses mais prováveis:

### **Hipótese 1: NOME DO VIZINHO COM ESPAÇOS/MAIÚSCULAS**

Se você configurou o nome de forma diferente nos dois computadores:

**No seu PC:**
```
Vizinho: "PC Colega"  (com espaço)
```

**No PC do colega:**
```
Nome do PC: "PCColega"  (sem espaço)
```

**Resultado:**
```python
msg.remetente_nome = "PCColega"        # Nome que vem na mensagem
self._historico = {
    "PC Colega": deque(...)             # Nome com espaço
}

# A verificação falha:
"PCColega" in {"PC Colega": ...}  # → FALSE!

# Nova entrada dinâmica é criada:
self._historico["PCColega"] = deque(...)

# Mas a GUI está olhando para "PC Colega":
viz_ativo = self.no.vizinhos[0].nome  # → "PC Colega"
chave = "PCColega"

if chave == viz_ativo:  # "PCColega" != "PC Colega" → FALSE!
    # Não redesenha!
```

### **Hipótese 2: VOCÊ ESTÁ EM OUTRA CONVERSA**

Se você tem múltiplos vizinhos e está visualizando outro:

```python
self._vizinho_ativo = 1  # Você está vendo outro vizinho
viz_ativo = self.no.vizinhos[1].nome  # "OutroPC"
chave = "PCColega"  # Mensagem chegou de PCColega

if chave == viz_ativo:  # "PCColega" != "OutroPC" → FALSE!
    # Não redesenha, apenas incrementa badge
else:
    self._contadores["PCColega"] += 1  # Badge deveria aparecer
```

Neste caso, o **badge de notificação** deveria aparecer na sidebar.

## 🔬 Como confirmar qual é o problema:

### **Teste 1: Adicione logs temporários**

Adicione prints no método `_processar` (linha ~288):

```python
def _processar(self, msg: Mensagem):
    print(f"\n=== MENSAGEM RECEBIDA ===")
    print(f"Remetente: '{msg.remetente_nome}'")
    print(f"Conteúdo: '{msg.conteudo}'")
    print(f"Histórico atual tem: {list(self._historico.keys())}")
    
    with self._lock:
        if (msg.encaminhado and msg.encaminhado_por
                and msg.encaminhado_por in self._historico):
            chave = msg.encaminhado_por
            print(f"→ Rota: encaminhado por {chave}")
        elif msg.remetente_nome in self._historico:
            chave = msg.remetente_nome
            print(f"→ Rota: remetente conhecido {chave}")
        else:
            chave = msg.remetente_nome
            print(f"→ Rota: NOVO remetente {chave}")
            self._historico[chave] = deque(maxlen=300)
            self._brutas[chave]    = deque(maxlen=50)
```

E no método `_processar_nova_msg` (linha ~1197):

```python
def _processar_nova_msg(self, chave: str):
    print(f"\n=== GUI CALLBACK ===")
    print(f"Chave recebida: '{chave}'")
    print(f"Vizinho ativo: '{self.no.vizinhos[self._vizinho_ativo].nome}'")
    print(f"Match? {chave == self.no.vizinhos[self._vizinho_ativo].nome}")
    
    self._pkt_count += 1
    self._pkt_var.set(f"PKT RX: {self._pkt_count}")
    
    viz_ativo = self.no.vizinhos[self._vizinho_ativo].nome
    
    if chave == viz_ativo:
        print("→ REDESENHANDO mensagens!")
        self._redesenhar_mensagens()
    else:
        print("→ Incrementando badge")
        # ...resto do código
```

### **Teste 2: Verificar nomes exatos**

Rode este comando em cada PC antes de conectar:

```bash
# No terminal do PC A
python3 -c "
no_a = 'MeuPC'
vizinho_a = 'PCColega'
print(f'PC A - Nome: |{no_a}| (len={len(no_a)})')
print(f'PC A - Vizinho: |{vizinho_a}| (len={len(vizinho_a)})')
"

# No terminal do PC B
python3 -c "
no_b = 'PCColega'
vizinho_b = 'MeuPC'
print(f'PC B - Nome: |{no_b}| (len={len(no_b)})')
print(f'PC B - Vizinho: |{vizinho_b}| (len={len(vizinho_b)})')
"
```

Compare se os nomes são **EXATAMENTE IGUAIS** (sem espaços extras, mesmas maiúsculas).

## ✅ Solução Preventiva

### **Opção 1: Normalização de nomes (mais robusta)**

Modificar a classe `Vizinho` para normalizar nomes:

```python
@dataclass
class Vizinho:
    nome: str
    ip: str
    porta: int
    
    def __post_init__(self):
        # Remove espaços extras e padroniza
        self.nome = self.nome.strip()
```

E no `No.__init__`:

```python
def __init__(self, nome: str, ip: str, porta: int, vizinhos: List[Vizinho]):
    self.nome = nome.strip()  # Normaliza o próprio nome também
    # ...
```

### **Opção 2: Debug visual na GUI**

Adicionar um label mostrando os nomes exatos:

```python
# No header da conversa, mostrar:
self._conv_sub.configure(
    text=f"  {viz.ip}:{viz.porta}  |  ID: '{viz.nome}'"
)
```

Isso deixa visível se há diferença nos nomes.

## 🎯 Checklist de diagnóstico rápido:

1. ✅ **Os ACKs funcionam** (você vê ✓✓) → UDP está funcionando
2. ❓ **Nomes são EXATAMENTE iguais?**
   - `"MeuPC"` ≠ `"meupc"` ≠ `"Meu PC"` ≠ `"MeuPC "`
3. ❓ **Você está na conversa certa?**
   - Clique no nome do colega na sidebar
4. ❓ **O badge de notificação aparece?**
   - Se sim → problema de seleção de conversa
   - Se não → problema de roteamento de mensagem

## 📊 O que os logs devem mostrar (caso normal):

**Quando você recebe mensagem do colega:**
```
=== MENSAGEM RECEBIDA ===
Remetente: 'PCColega'
Conteúdo: 'Olá!'
Histórico atual tem: ['PCColega']
→ Rota: remetente conhecido PCColega

=== GUI CALLBACK ===
Chave recebida: 'PCColega'
Vizinho ativo: 'PCColega'
Match? True
→ REDESENHANDO mensagens!
```

**Se os nomes não batem:**
```
=== MENSAGEM RECEBIDA ===
Remetente: 'PCColega'
Conteúdo: 'Olá!'
Histórico atual tem: ['PC Colega']  ← DIFERENTE!
→ Rota: NOVO remetente PCColega     ← Cria entrada duplicada

=== GUI CALLBACK ===
Chave recebida: 'PCColega'
Vizinho ativo: 'PC Colega'          ← DIFERENTE!
Match? False                         ← NÃO BATE!
→ Incrementando badge
```

## 🚨 Ação imediata:

1. **Execute os Testes 1 e 2** acima
2. **Copie os prints do terminal** quando receber uma mensagem
3. **Me envie** os resultados e poderei confirmar exatamente onde está o problema

---

**Resumo:** O problema mais provável é **inconsistência nos nomes** configurados entre os dois PCs. O código UDP está funcionando (por isso os ACKs aparecem), mas a lógica de roteamento está colocando as mensagens em chaves diferentes do dicionário `_historico`.
