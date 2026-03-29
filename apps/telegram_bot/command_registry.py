"""
Command Registry

基于装饰器的命令注册、解析与 Help 生成
"""
import shlex
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

logger = logging.getLogger("bot")

@dataclass
class CommandSpec:
    func: Callable
    command: str
    pattern: str  # e.g. "set" for subcommand match
    description: str
    usage: str
    examples: List[str]
    group: str  # "Basic", "Config", "Execution", "Reporting"

class CommandRegistry:
    def __init__(self):
        self.commands: Dict[str, List[CommandSpec]] = {} # command -> [specs] (support subcommands)
        
    def register(self, command: str, description: str, usage: str, examples: List[str], group: str = "Basic", pattern: str = ""):
        """装饰器：注册命令"""
        if not usage or not examples:
            raise ValueError(f"Command {command} must have usage and examples")
            
        def decorator(func):
            spec = CommandSpec(
                func=func,
                command=command,
                pattern=pattern,
                description=description,
                usage=usage,
                examples=examples,
                group=group
            )
            if command not in self.commands:
                self.commands[command] = []
            self.commands[command].append(spec)
            # Sort by pattern length desc to match longest subcommand first
            self.commands[command].sort(key=lambda x: len(x.pattern), reverse=True)
            return func
        return decorator

    def dispatch(self, text: str, ctx: Dict[str, Any]) -> bool:
        """分发命令"""
        if not text.startswith("/"):
            return False
            
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
            
        if not tokens:
            return False
            
        root_cmd = tokens[0].lower()
        args = tokens[1:]
        
        if root_cmd not in self.commands:
            return False
            
        specs = self.commands[root_cmd]
        
        # Match Subcommand
        # specs are sorted by pattern length, so first match is best
        for spec in specs:
            if not spec.pattern:
                # Catch-all (default handler for this root cmd)
                # But if we have args, and there are other subcommands...
                # Ideally, empty pattern matches only if NO args match other patterns
                pass
            
            # If pattern is present, check if args start with it
            if spec.pattern:
                pat_tokens = spec.pattern.split()
                if len(args) >= len(pat_tokens):
                    # Check match
                    current_tokens = [a.lower() for a in args[:len(pat_tokens)]]
                    if current_tokens == [p.lower() for p in pat_tokens]:
                        # Match!
                        real_args = args[len(pat_tokens):]
                        return self._exec(spec, real_args, ctx)
        
        # Fallback to empty pattern (if exists)
        for spec in specs:
            if not spec.pattern:
                return self._exec(spec, args, ctx)
                
        return False
        
    def _exec(self, spec: CommandSpec, args: List[str], ctx: Dict[str, Any]) -> bool:
        try:
            # Parse flags
            flags = {}
            clean_args = []
            i = 0
            while i < len(args):
                curr = args[i]
                if curr.startswith("--"):
                    key = curr[2:]
                    # Boolean flag or value? Simple: treat as bool for now unless next is value
                    # But request requires --max N. 
                    # Simple parser: if next token doesn't start with -, treat as value
                    val = True
                    if i + 1 < len(args) and not args[i+1].startswith("-"):
                        val = args[i+1]
                        i += 1
                    flags[key] = val
                else:
                    clean_args.append(curr)
                i += 1
            
            # Construct Payload
            payload = {
                "args": clean_args,
                "flags": flags,
                "raw_args": " ".join(args)
            }
            spec.func(payload, ctx)
            return True
        except Exception as e:
            logger.error(f"Command execution error: {e}", exc_info=True)
            tg = ctx.get("tg")
            chat_id = ctx.get("chat_id")
            if tg and chat_id:
                tg.send_message(chat_id, f"❌ 命令执行错误: {str(e)}")
            return True

    def get_help_text(self) -> str:
        """生成帮助文档"""
        groups = {}
        for cmd_list in self.commands.values():
            for spec in cmd_list:
                if spec.group not in groups:
                    groups[spec.group] = []
                groups[spec.group].append(spec)
        
        lines = ["🤖 **ChemDeep Bot Help**\n"]
        
        # Fixed Order
        order = ["Basic", "Config", "Execution", "Reporting"]
        for g in order:
            if g in groups:
                lines.append(f"📌 *{g}*")
                for spec in groups[g]:
                    full_cmd = f"{spec.command} {spec.pattern}".strip()
                    lines.append(f"`{full_cmd}` - {spec.description}")
                    lines.append(f"  Usage: `{spec.usage}`")
                lines.append("")
                
        return "\n".join(lines)
