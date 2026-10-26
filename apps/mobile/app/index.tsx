import { SafeAreaView, ScrollView, StyleSheet, Text, View } from 'react-native';

const panels = [
  { label: 'Balance', value: 'Not connected', note: 'We never guess your bank balance' },
  { label: 'Expenses', value: 'No transactions yet', note: 'Transaction ingestion is coming' },
  { label: 'Goals', value: 'Start saving intentionally', note: 'Wishlist and forecasts are on the roadmap' },
];

export default function HomeScreen() {
  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.eyebrow}>FINANCE AI • PRIVATE BETA</Text>
        <Text style={styles.title}>Your money, made clearer.</Text>
        <Text style={styles.subtitle}>A privacy-first financial companion. This is a Day 1 interface, not a connected account.</Text>
        {panels.map(p => <View key={p.label} style={styles.card}>
          <Text style={styles.label}>{p.label}</Text>
          <Text style={styles.value}>{p.value}</Text>
          <Text style={styles.note}>{p.note}</Text>
        </View>)}
        <Text style={styles.footer}>No banking data is collected in this build.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#F6F7FA' },
  body: { padding: 24, paddingTop: 56, gap: 14 },
  eyebrow: { color: '#52637D', fontSize: 12, fontWeight: '700', letterSpacing: 1.2 },
  title: { color: '#10192A', fontSize: 32, fontWeight: '700', marginTop: 8 },
  subtitle: { color: '#556174', fontSize: 15, lineHeight: 23, marginBottom: 16 },
  card: { backgroundColor: '#FFFFFF', padding: 20, borderRadius: 20, borderWidth: 1, borderColor: '#E8ECF2' },
  label: { color: '#52637D', fontSize: 14 },
  value: { color: '#15233B', fontSize: 20, fontWeight: '700', marginTop: 8 },
  note: { color: '#69768A', fontSize: 13, marginTop: 6 },
  footer: { color: '#7B8799', fontSize: 12, textAlign: 'center', marginTop: 12 }
});
