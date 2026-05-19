using System;
using System.Collections.Generic;
using Axiom.Core.Capabilities;

namespace Axiom.Core.Bridge
{
    /// <summary>
    /// Registry of available capabilities.
    /// Maps tool_name strings to IAxiomCapability instances.
    /// </summary>
    public class ToolRegistry
    {
        private readonly Dictionary<string, IAxiomCapability> _capabilities
            = new Dictionary<string, IAxiomCapability>(StringComparer.OrdinalIgnoreCase);

        public void Register(IAxiomCapability capability)
        {
            _capabilities[capability.Name] = capability;
        }

        public bool TryGet(string name, out IAxiomCapability capability)
        {
            return _capabilities.TryGetValue(name, out capability);
        }

        public IEnumerable<string> ListNames()
        {
            return _capabilities.Keys;
        }
    }
}
