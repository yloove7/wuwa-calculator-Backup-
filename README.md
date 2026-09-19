# Guia das partes mais importantes do Tethys System

Este documento explica apenas as partes realmente relevantes e mais complexas do programa. Se você quer entender o que o aplicativo faz de verdade, estas são as áreas que precisam ser ensinadas com atenção.

---

## 1. Personagem: como usar a análise de dados do personagem

A primeira função importante do programa é carregar e interpretar um personagem.

### Passo a passo

1. No topo da interface, há um campo de busca para digitar o nome ou ID do personagem.
2. Digite o nome ou ID desejado.
3. Use a busca para localizar o personagem.
4. O programa mostra os dados do personagem: atributos, elemento, arma, habilidades e estatísticas.

### O que você deve olhar

Depois que o personagem é carregado, a parte mais importante é entender:

- qual é o elemento dele;
- qual arma e classe ele usa;
- quais habilidades ele possui;
- qual é o impacto do personagem no dano total;
- como os atributos influenciam a performance geral.

### Por que isso importa

Sem essa etapa, você não consegue montar uma equipe com lógica. O programa não é só uma lista visual; ele interpreta dados do personagem para que a equipe e o dano tenham sentido.

### Em resumo

A análise de personagem é a base. Todas as decisões depois dependem de entender corretamente esse dado.

---

## 2. Equipes: como montar composições corretas

A segunda parte complexa é a montagem de equipes.

### Estrutura da equipe

A aba de equipes trabalha com slots de personagens. Em geral, cada slot tem uma função dentro da composição:

- DPS principal: responsável pela maior parte do dano;
- suporte ou utilidade: ajuda a manter a performance da composição;
- apoio complementar: fecha gaps de sinergia e melhora a estabilidade.

### Passo a passo

1. Crie uma nova equipe ou selecione uma existente.
2. Escolha os personagens para cada slot.
3. Verifique se a composição está coerente.
4. Ajuste os personagens conforme o objetivo da equipe.
5. Salve a equipe para reutilizar depois.

### O que é mais importante aqui

Não basta só colocar personagens bons. O programa foi pensado para ajudar a avaliar:

- sinergia entre personagens;
- compatibilidade de elementos;
- impacto do suporte e do DPS;
- como a equipe funciona como conjunto, não como personagens isolados.

### Echos e sinergia

Um dos pontos mais importantes da equipe é o uso de Echos.

1. Selecione o personagem.
2. Abra a configuração de Echos.
3. Escolha os Echos que ele recebe.
4. Verifique como a equipe muda com a mudança de set e bônus.

Isso altera diretamente a performance da equipe. O programa tenta resumir isso para você mostrar:

- quais elementos estão presentes;
- quão bem a equipe se comunica;
- quais bônus de conjunto estão ativos;
- se a composição está equilibrada ou fraca.

### Regra prática

Quando a equipe está bem montada, o dano total não depende só do DPS. Depende também do suporte, do encaixe e da sinergia geral.

---

## 3. Análise de dano: o coração do programa

Esta é a parte mais importante, porque é onde a ferramenta transforma dados em decisão.

### Como funciona

Depois de montar a equipe, o programa calcula a performance da rota ou da composição. Ele mostra:

- dano total;
- DPS ou dano por segundo;
- comparação entre valores esperados e reais;
- progresso ou variação da performance;
- dados de comparação entre simulações ou rotações.

### Passo a passo

1. Carregue a equipe ou a simulação relevante.
2. Verifique os personagens e a configuração escolhida.
3. Execute a análise.
4. Observe os resultados principais.
5. Compare o desempenho geral com outras rotações ou equipes.

### O que você precisa interpretar

Você não lê apenas um número isolado. O que importa é entender:

- quanto dano a composição realmente gera;
- se a rotação está estável;
- se a equipe está sendo eficiente ou se há margem de melhora;
- quais ajustes mudam o resultado de forma real.

### Botões de análise

Na parte de análise, alguns botões têm papel específico:

- Geral: mostra o resultado principal da simulação ou rotação.
- Por Segundo: mostra o rendimento temporal, útil para comparar DPS.
- Editar: permite ajustar a equipe ativa e testar outra composição sem perder o contexto.

Esses botões não são decorativos. Eles são a forma de alternar entre visão geral, rendimento temporal e ajuste da equipe.

---

## 4. Histórico: guardar e comparar resultados

A parte de histórico é onde o programa organiza tudo o que foi calculado.

### O que o histórico faz

Ele salva:

- equipe usada;
- nome da rotação ou cálculo;
- dano total;
- dados do resultado;
- comparação entre diferentes simulações.

### Passo a passo

1. Depois da análise, salve o resultado.
2. Dê um nome para a rotação ou cálculo.
3. O programa registra a entrada no histórico.
4. Quando quiser, você pode comparar o resultado com outro cálculo anterior.

### Por que isso é útil

Porque o problema real não é só calcular uma vez. O problema é saber:

- qual equipe produz mais dano;
- qual rotação foi melhor;
- qual configuração vale a pena manter;
- o que mudou entre uma simulação e outra.

### Importação e exportação

O programa também permite:

- importar um histórico em JSON;
- exportar os dados salvos para outro arquivo.

Isso é útil para backups, comparação externa ou organização entre sessões.

---

## 5. Vídeo e análise de dano em tempo real

Esta é outra área técnica e importante. O programa também pode analisar dano a partir de vídeo.

### Para que serve essa parte

Em vez de confiar só em dados internos, o programa tenta ler dano e desempenho a partir de um vídeo do combate.

### Passo a passo

1. Abra um vídeo local.
2. Ajuste o ponto em que a análise começa.
3. Configure o tempo para ignorar vinheta ou introdução.
4. Defina o início da análise.
5. Inicie a leitura.
6. O programa tenta medir dano, gráficos e picos ao longo do tempo.

### O que ele tenta extrair do vídeo

- dano por segundo;
- dano acumulado;
- picos de dano;
- momentos mais fracos;
- comportamento da rota ao longo do tempo.

### Campo mais importante

Os campos de:

- Ignorar vinheta;
- Início da análise;

são cruciais, porque o vídeo pode ter material que não pertence à análise real. Sem ajustar isso, os números podem estar distorcidos.

### Regra prática

Essa parte serve para validar o desempenho da rotação com dados de vídeo, não só com cálculos teóricos.

---

## 6. Fluxo correto de uso do programa

Se você quer usar o programa da maneira correta, o fluxo ideal é este:

1. Carregar o personagem principal.
2. Entender seus atributos e habilidades.
3. Montar a equipe no modo de equipes.
4. Ajustar Echos e sinergia.
5. Rodar a análise de dano.
6. Salvar a simulação no histórico.
7. Comparar os resultados.
8. Validar com vídeo, se necessário.

Esse é o ciclo principal da ferramenta.

---

## 7. Resumo prático

As partes que realmente importam e precisam ser entendidas são apenas estas:

- análise de personagem;
- montagem de equipe;
- Echos e sinergia;
- análise de dano;
- histórico e comparação;
- vídeo / análise real da rota.

Essas são as funções que têm lógica, cálculo e tomada de decisão. O resto é contextual ou visual, mas não é o núcleo do programa.
