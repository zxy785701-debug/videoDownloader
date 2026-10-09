// Interpret the generated policy subset using RFC 9309 group selection and
// longest-path precedence. This verifies policy semantics, not bot compliance.
export function robotsAllowed(text, agent, path) {
  const groups = []
  let current = { agents: [], rules: [] }, hasRules = false
  for (const raw of text.split('\n')) {
    const line = raw.split('#')[0].trim()
    const match = line.match(/^(user-agent|allow|disallow):\s*(.*)$/i)
    if (!match) continue
    const key = match[1].toLowerCase(), value = match[2].trim()
    if (key === 'user-agent') {
      if (hasRules) { groups.push(current); current = { agents: [], rules: [] }; hasRules = false }
      current.agents.push(value.toLowerCase())
    } else {
      hasRules = true
      if (value) current.rules.push({ allow: key === 'allow', value })
    }
  }
  groups.push(current)
  const token = agent.toLowerCase()
  const specific = groups.filter(group => group.agents.includes(token))
  const selected = specific.length ? specific : groups.filter(group => group.agents.includes('*'))
  const matches = selected.flatMap(group => group.rules).filter(rule => {
    const end = rule.value.endsWith('$'), prefix = end ? rule.value.slice(0, -1) : rule.value
    return end ? path === prefix : path.startsWith(prefix)
  }).sort((a, b) => b.value.replace(/\$$/, '').length - a.value.replace(/\$$/, '').length || Number(b.allow) - Number(a.allow))
  return matches[0]?.allow ?? true
}
