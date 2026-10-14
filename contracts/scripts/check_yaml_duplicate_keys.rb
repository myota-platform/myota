#!/usr/bin/env ruby
# Reject duplicate mapping keys in YAML before parsers can silently overwrite
# one declaration with another. OpenAPI uses scalar mapping keys throughout.
require "psych"

def duplicate_key_errors(node, context = "$", errors = [])
  case node
  when Psych::Nodes::Mapping
    seen = {}
    node.children.each_slice(2) do |key, value|
      unless key.is_a?(Psych::Nodes::Scalar)
        errors << "#{context}: non-scalar mapping keys are unsupported " \
                  "(line #{key.start_line + 1})"
        next
      end

      name = key.value
      if seen.key?(name)
        errors << "#{context}: duplicate mapping key #{name.inspect} " \
                  "at lines #{seen.fetch(name)} and #{key.start_line + 1}"
      else
        seen[name] = key.start_line + 1
      end
      duplicate_key_errors(value, "#{context}.#{name}", errors)
    end
  when Psych::Nodes::Sequence
    node.children.each_with_index do |child, index|
      duplicate_key_errors(child, "#{context}[#{index}]", errors)
    end
  else
    if node.respond_to?(:children) && node.children
      node.children.each_with_index do |child, index|
        duplicate_key_errors(child, "#{context}[#{index}]", errors)
      end
    end
  end
  errors
end

def errors_for(source, filename)
  duplicate_key_errors(Psych.parse_stream(source, filename: filename))
end

if ARGV == ["--self-test"]
  duplicate = errors_for("root:\n  item: 1\n  item: 2\n", "<self-test>")
  unless duplicate.any? { |error| error.include?("duplicate mapping key") }
    abort "self-test failed: duplicate mapping key was accepted"
  end

  siblings = errors_for(
    "left:\n  item: 1\nright:\n  item: 2\n",
    "<self-test>"
  )
  unless siblings.empty?
    abort "self-test failed: keys in separate mappings conflicted"
  end

  puts "Duplicate YAML key checker self-test passed"
  exit 0
end

unless ARGV.length == 1
  abort "usage: ruby scripts/check_yaml_duplicate_keys.rb <yaml-file>"
end

filename = ARGV.fetch(0)
errors = errors_for(File.read(filename, encoding: "UTF-8"), filename)
unless errors.empty?
  warn errors.map { |error| "#{filename}: #{error}" }.join("\n")
  exit 1
end

puts "No duplicate YAML mapping keys in #{filename}"
